"""Maya Collector — URL normalization, directory extraction, canonical domain deduplication, SQLite candidate registration.

Responsibilities:
- Normalize raw search result URLs to canonical domain
- Filter out non-prospect directory/blog/social domains (`NON_PROSPECT_DOMAINS`) while extracting
  embedded store domains from directory results (e.g., StoreLeads)
- Deduplicate by canonical domain (`INSERT OR IGNORE` into SQLite `candidates` table)
- Track `domains_seen` on the session to prevent re-discovery across hops
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Set
import urllib.parse
import uuid

from app.agents.schemas.evidence import compute_evidence_content_hash
from app.agents.schemas.session import ResearchSession
from app.db.connection import DB_PATH, get_connection, transaction

logger = logging.getLogger(__name__)

MAX_SNIPPET_CHARS = 1000
MAX_COMPANY_NAME_CHARS = 200

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

_DOMAIN_REGEX = re.compile(
    r"\b([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:myshopify\.com|co\.in|in|com|shop|store|org))\b",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_non_prospect_domain(domain: str) -> bool:
    d = (domain or "").lower().strip()
    if d.startswith("www."):
        d = d[4:]
    if d in NON_PROSPECT_DOMAINS:
        return True
    for bad in NON_PROSPECT_DOMAINS:
        if d.endswith("." + bad):
            return True
    return False


def _normalize_url(url: str) -> str:
    """Normalize a URL to lowercase scheme+host without trailing slash or www prefix."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        scheme = parsed.scheme.lower() or "https"
        port = parsed.port
        if port and ((scheme == "https" and port != 443) or (scheme == "http" and port != 80)):
            host = f"{host}:{port}"
        return f"{scheme}://{host}"
    except Exception:  # noqa: BLE001
        return url


def _canonical_domain(url: str) -> str:
    """Extract the canonical domain (no scheme, no www, no port for standard ports)."""
    normalized = _normalize_url(url)
    try:
        parsed = urllib.parse.urlparse(normalized)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:  # noqa: BLE001
        return url.lower()


def _clean_company_name_from_domain(domain: str) -> str:
    d = (domain or "").lower().strip()
    if d.startswith("www."):
        d = d[4:]
    if ".myshopify.com" in d:
        base = d.split(".myshopify.com")[0]
        base = re.sub(r"-\d+$", "", base)
        return base.replace("-", " ").title()
    parts = d.split(".")
    return parts[0].replace("-", " ").title()


def _extract_company_name(title: str, url: str) -> str:
    """Best-effort company name from search result title."""
    name = (title or "").split("|")[0].split(" - ")[0].split(" – ")[0].strip()
    if name and len(name) <= 50:
        return name[:MAX_COMPANY_NAME_CHARS]
    return _clean_company_name_from_domain(_canonical_domain(url))


def _extract_domains_from_text(text: str) -> List[str]:
    found: List[str] = []
    for match in _DOMAIN_REGEX.finditer(text or ""):
        d = match.group(1).lower().strip()
        if d.startswith("www."):
            d = d[4:]
        if any(d.endswith(ext) for ext in (".png", ".jpg", ".svg", ".js", ".css")):
            continue
        if not is_non_prospect_domain(d) and d not in found:
            found.append(d)
    return found


def _extract_window_around(text: str, needle: str, window: int = 220) -> str:
    idx = (text or "").lower().find(needle.lower())
    if idx == -1:
        return (text or "")[:window]
    start = max(0, idx - 80)
    end = min(len(text), idx + len(needle) + window)
    return text[start:end].strip()


class MayaCollector:
    """Registers candidate leads into the SQLite candidates table with provenance."""

    def __init__(self, session: ResearchSession, db_path: Optional[str] = None) -> None:
        self.session = session
        self._explicit_db_path = db_path

    @property
    def _db_path(self) -> str:
        import app.db.connection as _conn_mod
        return self._explicit_db_path or _conn_mod.DB_PATH


    def register_from_search_results(
        self,
        search_results: List[Dict[str, Any]],
        hop: int,
    ) -> List[str]:
        """Register new candidates from a list of raw search hit dicts.

        Returns list of candidate IDs that were newly inserted (not already seen).
        """
        inserted_ids: List[str] = []

        for hit in search_results:
            if (self.session.candidates_found or 0) >= self.session.max_candidates:
                break

            url = (hit.get("url") or "").strip()
            if not url:
                continue

            canonical = _canonical_domain(url)
            if not canonical:
                continue

            title = hit.get("title") or ""
            snippet = (hit.get("content") or hit.get("snippet") or "")[:MAX_SNIPPET_CHARS]

            # Case A: Directory or non-prospect domain (e.g. storeleads.app) containing embedded store domains
            if is_non_prospect_domain(canonical):
                extracted_domains = _extract_domains_from_text(f"{title}\n{snippet}")
                for dom in extracted_domains:
                    if (self.session.candidates_found or 0) >= self.session.max_candidates:
                        break
                    if dom in (self.session.domains_seen or []) or is_non_prospect_domain(dom):
                        continue
                    excerpt = _extract_window_around(snippet, dom, window=240)
                    company_name = _clean_company_name_from_domain(dom)
                    cid = self._insert_candidate(
                        canonical_domain=dom,
                        initial_url=f"https://{dom}",
                        company_name=company_name,
                        discovered_from_url=url,
                        discovery_hop=hop,
                        snippet_context=excerpt,
                    )
                    if cid:
                        inserted_ids.append(cid)
                        if dom not in (self.session.domains_seen or []):
                            self.session.domains_seen.append(dom)
                        self.session.candidates_found = (self.session.candidates_found or 0) + 1
                        if "storeleads.app" in canonical:
                            self._bind_directory_evidence(cid, dom, url, excerpt)
                continue

            # Case B: Direct prospect domain
            if canonical in (self.session.domains_seen or []):
                continue

            company_name = _extract_company_name(title, url)
            normalized = _normalize_url(url)

            cid = self._insert_candidate(
                canonical_domain=canonical,
                initial_url=normalized,
                company_name=company_name,
                discovered_from_url=url,
                discovery_hop=hop,
                snippet_context=snippet,
            )

            if cid:
                inserted_ids.append(cid)
                if canonical not in (self.session.domains_seen or []):
                    self.session.domains_seen.append(canonical)
                self.session.candidates_found = (self.session.candidates_found or 0) + 1

        logger.info(
            "[Collector][session=%s] hop=%d: %d results → %d new candidates registered",
            self.session.id,
            hop,
            len(search_results),
            len(inserted_ids),
        )
        return inserted_ids

    def _insert_candidate(
        self,
        *,
        canonical_domain: str,
        initial_url: str,
        company_name: str,
        discovered_from_url: str,
        discovery_hop: int,
        snippet_context: str = "",
    ) -> Optional[str]:
        """INSERT OR IGNORE a candidate row and default low-observability claims."""
        cid = f"C{uuid.uuid4().hex[:10]}"
        _now = _utc_now()
        try:
            with transaction(self._db_path) as conn:
                existing = conn.execute(
                    "SELECT id FROM candidates WHERE session_id=? AND canonical_domain=?",
                    (self.session.id, canonical_domain),
                ).fetchone()
                if existing:
                    return None

                conn.execute(
                    """
                    INSERT OR IGNORE INTO candidates (
                        id, session_id, company_name, canonical_domain, initial_url,
                        discovered_from_url, discovery_hop, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        self.session.id,
                        company_name,
                        canonical_domain,
                        initial_url,
                        discovered_from_url,
                        discovery_hop,
                        _now,
                        _now,
                    ),
                )

                # Initialize default claims for low-observability fields
                default_claims = [
                    ("revenue", "UNVERIFIED (Private entity)", "UNVERIFIED"),
                    ("paid_app_subscription", "UNVERIFIED (Billing tier not publicly observable)", "UNVERIFIED"),
                    ("performance_audit", "NOT AUDITED (Requires speed test)", "NOT_AUDITED"),
                ]
                for field_name, val, status in default_claims:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO claims (
                            id, session_id, candidate_id, field, value, status, version, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                        """,
                        (f"clm_{cid}_{field_name}", self.session.id, cid, field_name, val, status, _now),
                    )
            return cid
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Collector] Failed to insert candidate domain=%s: %s", canonical_domain, exc
            )
            return None

    def _bind_directory_evidence(
        self,
        candidate_id: str,
        canonical_domain: str,
        source_url: str,
        excerpt: str,
    ) -> None:
        """Bind StoreLeads directory evidence for platform and installed apps."""
        lower = (excerpt or "").lower()
        _now = _utc_now()
        try:
            with transaction(self._db_path) as conn:
                if "shopify" in lower or "shopify" in source_url.lower() or ".myshopify.com" in canonical_domain:
                    ev_id = f"E{uuid.uuid4().hex[:12]}"
                    c_hash = compute_evidence_content_hash(
                        candidate_id=candidate_id,
                        source_url=source_url,
                        source_type="storeleads_directory",
                        supports_field="platform",
                        signal_type="directory_listing:shopify",
                        extracted_value="Shopify",
                        raw_excerpt=excerpt[:500],
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO evidence (
                            id, session_id, candidate_id, verifier_version,
                            source_url, source_type, supports_field, signal_type,
                            extracted_value, raw_excerpt, confidence, content_hash, retrieved_at
                        ) VALUES (?, ?, ?, 'v2.0', ?, 'storeleads_directory', 'platform',
                                  'directory_listing:shopify', 'Shopify', ?, 'HIGH', ?, ?)
                        """,
                        (ev_id, self.session.id, candidate_id, source_url, excerpt[:500], c_hash, _now),
                    )
                    claim_id = f"clm_{candidate_id}_platform"
                    conn.execute(
                        """
                        INSERT INTO claims (id, session_id, candidate_id, field, value, status, version, updated_at)
                        VALUES (?, ?, ?, 'platform', 'Shopify', 'SUPPORTED', 1, ?)
                        ON CONFLICT(candidate_id, field) DO UPDATE SET
                            value='Shopify', status='SUPPORTED', version=claims.version+1, updated_at=excluded.updated_at
                        """,
                        (claim_id, self.session.id, candidate_id, _now),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO claim_evidence (claim_id, evidence_id, session_id, candidate_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (claim_id, ev_id, self.session.id, candidate_id),
                    )

                detected_apps = [
                    app_name
                    for app_name in ("Wati", "Nudgify", "Fera", "Easysize", "Judge.me", "Loox", "Smile.io", "Klaviyo")
                    if app_name.lower() in lower
                ]
                if detected_apps:
                    apps_str = ", ".join(detected_apps)
                    ev_id = f"E{uuid.uuid4().hex[:12]}"
                    c_hash = compute_evidence_content_hash(
                        candidate_id=candidate_id,
                        source_url=source_url,
                        source_type="storeleads_directory",
                        supports_field="installed_apps",
                        signal_type="directory_listing:apps",
                        extracted_value=apps_str,
                        raw_excerpt=excerpt[:500],
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO evidence (
                            id, session_id, candidate_id, verifier_version,
                            source_url, source_type, supports_field, signal_type,
                            extracted_value, raw_excerpt, confidence, content_hash, retrieved_at
                        ) VALUES (?, ?, ?, 'v2.0', ?, 'storeleads_directory', 'installed_apps',
                                  'directory_listing:apps', ?, ?, 'HIGH', ?, ?)
                        """,
                        (ev_id, self.session.id, candidate_id, source_url, apps_str, excerpt[:500], c_hash, _now),
                    )
                    claim_id = f"clm_{candidate_id}_installed_apps"
                    conn.execute(
                        """
                        INSERT INTO claims (id, session_id, candidate_id, field, value, status, version, updated_at)
                        VALUES (?, ?, ?, 'installed_apps', ?, 'SUPPORTED', 1, ?)
                        ON CONFLICT(candidate_id, field) DO UPDATE SET
                            value=excluded.value, status='SUPPORTED', version=claims.version+1, updated_at=excluded.updated_at
                        """,
                        (claim_id, self.session.id, candidate_id, apps_str, _now),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO claim_evidence (claim_id, evidence_id, session_id, candidate_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (claim_id, ev_id, self.session.id, candidate_id),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Collector] Failed to bind directory evidence for %s: %s", candidate_id, exc)

    def get_unaudited_candidates(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return unaudited candidate rows from SQLite for this session."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, canonical_domain, initial_url, company_name,
                       discovered_from_url, discovery_hop
                FROM candidates
                WHERE session_id=? AND audited_by_verifier=0
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (self.session.id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_audited(self, candidate_id: str) -> None:
        """Mark a candidate as having been submitted to DomainVerificationService."""
        try:
            with transaction(self._db_path) as conn:
                conn.execute(
                    "UPDATE candidates SET audited_by_verifier=1 WHERE id=?",
                    (candidate_id,),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Collector] mark_audited(%s) failed: %s", candidate_id, exc)
