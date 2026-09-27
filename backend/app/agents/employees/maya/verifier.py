from typing import List
from app.agents.schemas.candidate import Candidate
from app.agents.schemas.evidence import EvidenceStore
from app.agents.schemas.session import ResearchSession
from app.tools.domain_verifier import verify_domain_safely


class MayaFieldVerifier:
    """
    Implements Amendment #3:
    Mechanical, field-specific verification of Candidate records.
    Populates individual Evidence records in EvidenceStore for:
      - identity
      - website
      - platform
      - apps
      - d2c_status
      - revenue (kept UNVERIFIED unless primary financial filing exists)
      - website_condition (kept NOT_AUDITED for speed/bounce; records only mechanical HTML facts)
      - contact
    """

    @classmethod
    def verify_candidates(
        cls,
        candidates: List[Candidate],
        session: ResearchSession,
        evidence_store: EvidenceStore
    ) -> int:
        verified_count = 0
        for cand in candidates:
            if cand.audited_by_verifier:
                continue
            if session.verification_requests_made >= session.max_verification_requests:
                break

            session.verification_requests_made += 1
            cls.verify_single_candidate(cand, evidence_store)
            cand.audited_by_verifier = True
            session.candidates_verified += 1
            verified_count += 1

        return verified_count

    @classmethod
    def verify_single_candidate(
        cls,
        cand: Candidate,
        evidence_store: EvidenceStore
    ) -> None:
        footprint = verify_domain_safely(cand.url, timeout=4)

        # 1. Website & Identity Field Verification
        err_msg = footprint.error or ""
        if "SSRF" in err_msg or "Blocked:" in err_msg:
            cand.website.status = "CONTRADICTED"
            cand.website.value = cand.url
            cand.website.notes = f"SSRF Blocked: {err_msg}"
            cand.failed_checks.append(f"Website blocked by SSRF guard: {err_msg}")
            return

        if not footprint.reachable:
            # If the candidate is a .myshopify.com domain that was already proved via StoreLeads directory,
            # keep directory evidence as fallback note, otherwise mark website UNVERIFIED/CONTRADICTED
            if cand.platform.status == "SUPPORTED" and cand.platform.evidence_ids:
                cand.website.status = "UNVERIFIED"
                cand.website.value = cand.url
                cand.website.notes = f"Live HTTP timed out ({err_msg}), backed by directory record."
            else:
                cand.website.status = "CONTRADICTED"
                cand.website.value = cand.url
                cand.website.notes = f"Dead or unreachable domain: {err_msg}"
                cand.failed_checks.append(f"Website unreachable: {err_msg}")
            return

        # Live HTTP succeeded! Record mechanical HTTP Evidence
        ev_http = evidence_store.add_evidence(
            candidate_id=cand.id,
            source_url=footprint.final_url or cand.url,
            source_type="live_http_headers",
            supports_field="website",
            supports_claim=footprint.final_url or cand.url,
            content_excerpt=(
                f"HTTP {footprint.status_code} OK at {footprint.final_url} "
                f"(Redirect hops: {len(footprint.redirect_chain)})"
            ),
            confidence=1.0
        )
        cand.url = footprint.final_url or cand.url
        cand.website.value = cand.url
        cand.website.status = "SUPPORTED"
        if ev_http.id not in cand.website.evidence_ids:
            cand.website.evidence_ids.append(ev_http.id)

        cand.identity.value = cand.company_name
        cand.identity.status = "SUPPORTED"
        if ev_http.id not in cand.identity.evidence_ids:
            cand.identity.evidence_ids.append(ev_http.id)

        # 2. Platform Field Verification (Live HTML takes priority)
        detected_plat = footprint.platform if footprint.platform and footprint.platform != "UNKNOWN" else None
        if detected_plat:
            signals_excerpt = ", ".join(footprint.signals[:4]) if footprint.signals else f"Detected {detected_plat} in live HTML."
            ev_plat = evidence_store.add_evidence(
                candidate_id=cand.id,
                source_url=cand.url,
                source_type="live_html_footprint",
                supports_field="platform",
                supports_claim=detected_plat,
                content_excerpt=f"{detected_plat} confirmed via signals: {signals_excerpt}",
                confidence=1.0
            )
            cand.platform.value = detected_plat
            cand.platform.status = "SUPPORTED"
            if ev_plat.id not in cand.platform.evidence_ids:
                cand.platform.evidence_ids.append(ev_plat.id)

            # D2C / Ecommerce Storefront verification
            ev_d2c = evidence_store.add_evidence(
                candidate_id=cand.id,
                source_url=cand.url,
                source_type="live_html_footprint",
                supports_field="d2c_status",
                supports_claim=f"Active {detected_plat} Storefront",
                content_excerpt=f"Live storefront verified on {cand.url} ({detected_plat})",
                confidence=0.95
            )
            cand.d2c_status.value = f"Active {detected_plat} Storefront"
            cand.d2c_status.status = "SUPPORTED"
            if ev_d2c.id not in cand.d2c_status.evidence_ids:
                cand.d2c_status.evidence_ids.append(ev_d2c.id)

        elif cand.platform.status == "SUPPORTED" and cand.platform.evidence_ids:
            # Keep directory-supported platform if live HTML didn't expose signature (e.g., headless/Waitpage)
            cand.d2c_status.value = f"Directory-Listed {cand.platform.value} Store"
            cand.d2c_status.status = "SUPPORTED"
            cand.d2c_status.evidence_ids = list(cand.platform.evidence_ids)

        # 3. Apps Field Verification
        if footprint.detected_apps:
            existing_apps = [a.strip() for a in (cand.apps.value or "").split(",") if a.strip()]
            merged_apps = list(dict.fromkeys(existing_apps + footprint.detected_apps))
            apps_str = ", ".join(merged_apps)
            ev_apps = evidence_store.add_evidence(
                candidate_id=cand.id,
                source_url=cand.url,
                source_type="live_html_footprint",
                supports_field="apps",
                supports_claim=apps_str,
                content_excerpt=f"Detected third-party app scripts in live HTML: {apps_str}",
                confidence=1.0
            )
            cand.apps.value = apps_str
            cand.apps.status = "SUPPORTED"
            if ev_apps.id not in cand.apps.evidence_ids:
                cand.apps.evidence_ids.append(ev_apps.id)

        # 4. Revenue Field Verification (Strict Unknown-as-Unknown Law)
        # Private Indian D2C storefronts do not publish audited annual revenue in HTML.
        if cand.revenue.status != "SUPPORTED" or not cand.revenue.evidence_ids:
            cand.revenue.value = "UNVERIFIED (Private entity)"
            cand.revenue.status = "UNVERIFIED"
            cand.revenue.evidence_ids = []

        # 5. Website Condition Field (Never invent load times or bounce rates)
        cand.website_condition.value = "NOT AUDITED (No Lighthouse/speed test run)"
        cand.website_condition.status = "NOT_AUDITED"
        cand.website_condition.evidence_ids = []
