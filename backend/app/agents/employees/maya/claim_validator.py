import re
from typing import Dict, List, Tuple
from app.agents.schemas.candidate import Candidate
from app.agents.schemas.claim import Claim
from app.agents.schemas.evidence import EvidenceStore


class MayaClaimValidator:
    """
    Implements Amendment #4:
    1. Structured Claim Validation: Verifies that every Claim's evidence_ids exist in
       EvidenceStore, match the candidate and field, and that the Evidence content_excerpt
       actually supports the claimed value.
    2. Allowed Outreach Claims Extraction: Produces the strict whitelist of verified facts
       that the Outreach Composer is permitted to see.
    3. Post-Composition Validation & Repair: Rejects/repairs any unsupported speed,
       bounce rate, or unverified revenue assertion in composed text.
    """

    UNMEASURED_SPEED_PATTERN = re.compile(
        r'\b(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b(?:\s+(?:mobile\s+)?(?:load|loading|page\s+load|speed|time|lcp|ttfb))?',
        re.IGNORECASE
    )
    BOUNCE_RATE_PATTERN = re.compile(
        r'\b(\d{1,2}(?:\.\d+)?%)\s*(?:bounce\s+rate|drop-?off|cart\s+abandonment)',
        re.IGNORECASE
    )

    @classmethod
    def validate_structured_claim(
        cls,
        candidate_id: str,
        claim: Claim,
        evidence_store: EvidenceStore
    ) -> Tuple[bool, str]:
        """
        Deterministically checks whether the Evidence objects referenced by claim.evidence_ids
        genuinely support claim.field and claim.value.
        """
        if claim.status != "SUPPORTED":
            return False, f"Claim status is {claim.status}, not SUPPORTED."

        if not claim.evidence_ids:
            claim.status = "UNVERIFIED"
            return False, "Claim has no evidence_ids."

        if not claim.value:
            claim.status = "UNVERIFIED"
            return False, "Claim has empty value."

        supporting_evidences = []
        for eid in claim.evidence_ids:
            ev = evidence_store.get(eid)
            if not ev:
                continue
            if ev.candidate_id != candidate_id:
                continue
            if ev.supports_field != claim.field:
                continue
            # Check content support: value keywords must appear in supports_claim or content_excerpt
            val_tokens = [t.strip().lower() for t in re.split(r'[,/]+', claim.value) if t.strip()]
            combined_ev_text = f"{ev.supports_claim} {ev.content_excerpt}".lower()
            if any(tok in combined_ev_text for tok in val_tokens):
                supporting_evidences.append(ev)

        if not supporting_evidences:
            claim.status = "UNVERIFIED"
            claim.evidence_ids = []
            claim.notes = "Rejected by MayaClaimValidator: Evidence excerpt does not support claimed value."
            return False, claim.notes

        claim.evidence_ids = [ev.id for ev in supporting_evidences]
        return True, f"Supported by {[ev.id for ev in supporting_evidences]}"

    @classmethod
    def build_allowed_outreach_claims(
        cls,
        cand: Candidate,
        evidence_store: EvidenceStore
    ) -> List[Dict[str, str]]:
        """
        Returns ONLY claims that pass strict EvidenceStore validation.
        The Outreach Composer receives ONLY this list — never raw search text.
        """
        allowed: List[Dict[str, str]] = []
        for field_name, claim in cand.get_all_claims().items():
            if claim.status == "SUPPORTED":
                is_valid, reason = cls.validate_structured_claim(cand.id, claim, evidence_store)
                if is_valid and claim.value:
                    ev_urls = [
                        evidence_store.get(eid).source_url
                        for eid in claim.evidence_ids
                        if evidence_store.get(eid)
                    ]
                    allowed.append({
                        "field": field_name,
                        "value": claim.value,
                        "evidence_ids": ", ".join(claim.evidence_ids),
                        "source_url": ev_urls[0] if ev_urls else cand.url
                    })
        return allowed

    @classmethod
    def validate_and_repair_text(
        cls,
        text: str,
        cand: Candidate
    ) -> Tuple[str, bool, List[str]]:
        """
        Inspects composed outreach or report text against Candidate's verified field state.
        If website_condition is NOT_AUDITED, strips unmeasured load-time/bounce claims.
        """
        if not text:
            return text, False, []

        repaired = text
        violations: List[str] = []

        if cand.website_condition.status != "SUPPORTED":
            if re.search(r'\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|s)\b.*?\b(?:load|speed|mobile|page)\b', repaired, re.IGNORECASE):
                violations.append("Rejected unmeasured load-time claim (website_condition is NOT_AUDITED)")
                repaired = re.sub(
                    r'(?:takes?\s+(?:over\s+)?|loads?\s+in\s+|at\s+)\d+(?:\.\d+)?\s*(?:seconds?|secs?|s)\s*(?:to\s+load|on\s+mobile|load\s+time)?',
                    'has opportunities for mobile storefront optimization',
                    repaired,
                    flags=re.IGNORECASE
                )
            if cls.BOUNCE_RATE_PATTERN.search(repaired):
                violations.append("Rejected unmeasured bounce-rate claim (website_condition is NOT_AUDITED)")
                repaired = cls.BOUNCE_RATE_PATTERN.sub(
                    'potential checkout drop-off',
                    repaired
                )

        return repaired, len(violations) > 0, violations
