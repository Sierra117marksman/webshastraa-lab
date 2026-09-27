import re
import json
import urllib.parse
from typing import Any, Dict, List, Set
from app.agents.schemas.candidate import Candidate, CandidateLedger
from app.agents.schemas.evidence import EvidenceStore
from app.agents.schemas.session import ResearchSession


# Domains that are directories, blogs, or platforms — NEVER a D2C prospect's own storefront
NON_PROSPECT_DOMAINS: Set[str] = {
    "storeleads.app",
    "shopify.com",
    "apps.shopify.com",
    "wordpress.org",
    "wordpress.com",
    "woocommerce.com",
    "inc42.com",
    "yourstory.com",
    "vcwire.tech",
    "projectsupply.in",
    "entrackr.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "forbes.com",
    "forbesindia.com",
    "linkedin.com",
    "instagram.com",
    "facebook.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "reddit.com",
    "medium.com",
    "quora.com",
    "wikipedia.org",
    "google.com",
    "tavily.com",
    "clutch.co",
    "goodfirms.co",
    "g2.com",
    "capterra.com",
    "builtwith.com",
    "wappalyzer.com",
    "crunchbase.com",
    "tracxn.com",
    "ambitionbox.com",
    "glassdoor.com",
    "naukri.com",
    "indeed.com",
}


def is_non_prospect_domain(domain: str) -> bool:
    d = domain.lower().strip()
    if d.startswith("www."):
        d = d[4:]
    if d in NON_PROSPECT_DOMAINS:
        return True
    for bad in NON_PROSPECT_DOMAINS:
        if d.endswith("." + bad):
            return True
    return False


def clean_company_name_from_domain(domain: str) -> str:
    d = domain.lower().strip()
    if d.startswith("www."):
        d = d[4:]
    if ".myshopify.com" in d:
        base = d.split(".myshopify.com")[0]
        base = re.sub(r'-\d+$', '', base)
        return base.replace("-", " ").title()
    parts = d.split(".")
    return parts[0].replace("-", " ").title()


class MayaCollector:
    """
    Implements Amendment #2:
    Tier 1: Deterministic candidate & domain extraction from search results and directory tables.
    Tier 2: Optional targeted LLM extraction ONLY when search results are ambiguous listicles.
    """

    DOMAIN_REGEX = re.compile(
        r'\b([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:myshopify\.com|co\.in|in|com|shop|store|org))\b',
        re.IGNORECASE
    )

    @classmethod
    def collect_from_search_results(
        cls,
        search_results: List[Dict[str, Any]],
        session: ResearchSession,
        ledger: CandidateLedger,
        evidence_store: EvidenceStore,
        hop: int,
        llm_client: Any = None
    ) -> List[Candidate]:
        newly_added: List[Candidate] = []

        for item in search_results:
            if session.candidates_found >= session.max_candidates:
                break

            res_url = (item.get("url") or "").strip()
            res_title = (item.get("title") or "").strip()
            res_content = (item.get("content") or "").strip()
            if not res_url:
                continue

            parsed = urllib.parse.urlparse(res_url)
            host = (parsed.netloc or "").lower()
            if host.startswith("www."):
                host = host[4:]

            # Case A: Result is a StoreLeads directory report containing multiple real store domains
            if "storeleads.app" in host or is_non_prospect_domain(host):
                extracted_domains = cls._extract_domains_from_text(f"{res_title}\n{res_content}")
                for dom in extracted_domains:
                    if session.candidates_found >= session.max_candidates:
                        break
                    if is_non_prospect_domain(dom):
                        continue
                    # Extract a local excerpt around the domain mention
                    excerpt = cls._extract_window_around(res_content, dom, window=220)
                    company_name = clean_company_name_from_domain(dom)
                    cand = ledger.upsert_candidate(
                        company_name=company_name,
                        canonical_domain=dom,
                        url=f"https://{dom}",
                        discovered_from=res_url,
                        discovery_hop=hop,
                        snippet_context=excerpt
                    )
                    if cand:
                        if dom not in session.domains_seen:
                            session.domains_seen.append(dom)
                            session.candidates_found = len(ledger.candidates)
                            newly_added.append(cand)
                        # Record directory evidence if storeleads
                        if "storeleads.app" in host:
                            cls._bind_directory_evidence(cand, res_url, excerpt, evidence_store)
            else:
                # Case B: Result URL is a direct candidate company domain
                if not host or is_non_prospect_domain(host):
                    continue
                company_name = res_title.split("|")[0].split("-")[0].split("–")[0].strip()
                if len(company_name) > 40 or not company_name:
                    company_name = clean_company_name_from_domain(host)

                cand = ledger.upsert_candidate(
                    company_name=company_name,
                    canonical_domain=host,
                    url=f"{parsed.scheme or 'https'}://{host}",
                    discovered_from=res_url,
                    discovery_hop=hop,
                    snippet_context=f"{res_title}: {res_content[:300]}"
                )
                if cand and host not in session.domains_seen:
                    session.domains_seen.append(host)
                    session.candidates_found = len(ledger.candidates)
                    newly_added.append(cand)

        # Tier 2: Optional LLM extraction ONLY if deterministic pass found < 2 candidates from non-empty results
        if len(newly_added) < 2 and search_results and llm_client is not None:
            llm_extracted = cls._optional_llm_extract(search_results, session, llm_client)
            for item in llm_extracted:
                dom = (item.get("domain") or "").lower().strip()
                if dom.startswith("https://") or dom.startswith("http://"):
                    dom = urllib.parse.urlparse(dom).netloc.lower()
                if dom.startswith("www."):
                    dom = dom[4:]
                if not dom or "." not in dom or is_non_prospect_domain(dom):
                    continue
                name = item.get("company_name") or clean_company_name_from_domain(dom)
                cand = ledger.upsert_candidate(
                    company_name=name,
                    canonical_domain=dom,
                    url=f"https://{dom}",
                    discovered_from="llm_article_extraction",
                    discovery_hop=hop,
                    snippet_context=item.get("context", "")
                )
                if cand and dom not in session.domains_seen:
                    session.domains_seen.append(dom)
                    session.candidates_found = len(ledger.candidates)
                    newly_added.append(cand)

        return newly_added

    @classmethod
    def _extract_domains_from_text(cls, text: str) -> List[str]:
        found = []
        for match in cls.DOMAIN_REGEX.finditer(text):
            d = match.group(1).lower().strip()
            if d.startswith("www."):
                d = d[4:]
            # Ignore image/asset filenames that look like domains
            if any(d.endswith(ext) for ext in [".png", ".jpg", ".svg", ".js", ".css"]):
                continue
            if not is_non_prospect_domain(d) and d not in found:
                found.append(d)
        return found

    @staticmethod
    def _extract_window_around(text: str, needle: str, window: int = 220) -> str:
        idx = text.lower().find(needle.lower())
        if idx == -1:
            return text[:window]
        start = max(0, idx - 80)
        end = min(len(text), idx + len(needle) + window)
        return text[start:end].strip()

    @staticmethod
    def _bind_directory_evidence(
        cand: Candidate,
        source_url: str,
        excerpt: str,
        evidence_store: EvidenceStore
    ) -> None:
        lower = excerpt.lower()
        # Platform evidence from StoreLeads report
        if "shopify" in lower or "shopify" in source_url.lower() or ".myshopify.com" in cand.canonical_domain:
            ev = evidence_store.add_evidence(
                candidate_id=cand.id,
                source_url=source_url,
                source_type="storeleads_directory",
                supports_field="platform",
                supports_claim="Shopify",
                content_excerpt=excerpt,
                confidence=0.9
            )
            if ev.id not in cand.platform.evidence_ids:
                cand.platform.value = "Shopify"
                cand.platform.status = "SUPPORTED"
                cand.platform.evidence_ids.append(ev.id)

        # App evidence from StoreLeads snippet
        detected_apps = []
        for app_name in ["Wati", "Nudgify", "Fera", "Easysize", "Judge.me", "Loox", "Smile.io", "Klaviyo", "Razorpay"]:
            if app_name.lower() in lower:
                detected_apps.append(app_name)
        if detected_apps:
            apps_str = ", ".join(detected_apps)
            ev = evidence_store.add_evidence(
                candidate_id=cand.id,
                source_url=source_url,
                source_type="storeleads_directory",
                supports_field="apps",
                supports_claim=apps_str,
                content_excerpt=excerpt,
                confidence=0.9
            )
            cand.apps.value = apps_str
            cand.apps.status = "SUPPORTED"
            if ev.id not in cand.apps.evidence_ids:
                cand.apps.evidence_ids.append(ev.id)

    @staticmethod
    def _optional_llm_extract(
        search_results: List[Dict[str, Any]],
        session: ResearchSession,
        llm_client: Any
    ) -> List[Dict[str, str]]:
        from app.engine.llm_gateway import generate_content_with_retry
        snippets = "\n---\n".join(
            f"Title: {r.get('title')}\nURL: {r.get('url')}\nSnippet: {r.get('content', '')[:350]}"
            for r in search_results[:6]
        )
        prompt = (
            "Extract real, specific company domains mentioned in these search snippets.\n"
            "Return ONLY a raw JSON list of objects: [{\"company_name\": \"...\", \"domain\": \"example.com\", \"context\": \"...\"}].\n"
            "Do NOT invent domains. Only include explicit domains present in the text.\n\n"
            f"{snippets}"
        )
        try:
            session.llm_calls_made += 1
            session.tokens_in += max(1, len(prompt) // 4)
            res = generate_content_with_retry(
                client=llm_client,
                model="gemini-3.8-flash",
                contents=[{"role": "user", "parts": [{"text": prompt}]}]
            )
            raw = (res.text or "").strip()
            session.tokens_out += max(1, len(raw) // 4)
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1:
                return json.loads(raw[start:end + 1])
        except Exception:
            pass
        return []
