"""Maya ClaimValidator — excerpt provenance check, allowed_outreach_claims whitelist, and post-composition sanitization.

Key invariants:
- A claim is allowed for outreach ONLY if it has at least one Evidence row with HIGH/MEDIUM
  confidence and the raw_excerpt is non-empty and supports the extracted_value
- LOW_PUBLIC_OBSERVABILITY fields (revenue, paid_app_subscription, performance_audit)
  are NEVER placed in allowed_outreach_claims unless backed by authoritative financial/official filings
- Installed app script detection (`installed_apps`) NEVER upgrades `paid_app_subscription`
- Non-active `storefront_state` (`unknown`, `dead`, `password_locked`, `maintenance`) is NEVER placed in `allowed_outreach_claims`
- Post-composition validation rejects/sanitizes any hallucinated load-time seconds, bounce rates,
  paid-app billing assertions, unverified revenue figures, fabricated contact emails, or unwhitelisted apps/platforms
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.agents.schemas.requirement import AUTHORITATIVE_FINANCIAL_SOURCES, LOW_OBSERVABILITY_FIELDS
from app.agents.schemas.session import ResearchSession
import app.db.connection as _conn_mod
from app.db.connection import get_connection

logger = logging.getLogger(__name__)

OUTREACH_CONFIDENT_LEVELS = {"HIGH", "MEDIUM"}

_LOW_OBS_LABELS: Dict[str, str] = {
    "revenue": "UNVERIFIED (Private entity — revenue not publicly observable)",
    "paid_app_subscription": "UNVERIFIED (Billing tier not publicly observable)",
    "performance_audit": "NOT AUDITED (Requires independent speed test — not measured)",
}

_UNMEASURED_SPEED_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|s)\b.*?\b(?:load|loading|speed|mobile|page|lcp|ttfb)\b",
    re.IGNORECASE,
)
_BOUNCE_RATE_PATTERN = re.compile(
    r"\b(\d{1,2}(?:\.\d+)?%)\s*(?:bounce\s+rate|drop-?off|cart\s+abandonment)",
    re.IGNORECASE,
)
_PAID_APP_CLAIM_PATTERN = re.compile(
    r"\b(?:paid\s+(?:app|subscription|plan|tier)|paying\s+(?:for|in)\s+[a-z0-9._-]+)",
    re.IGNORECASE,
)
_REVENUE_CLAIM_PATTERN = re.compile(
    r"(?:₹\s*\d+(?:\.\d+)?\s*(?:lakh|lakhs|l|cr|crore|crores)?|\b\d+(?:\.\d+)?\s*(?:lakh|lakhs|crore|crores)\b|\$\s*\d+(?:\.\d+)?\s*[mkb]\s*(?:revenue|turnover|arr))",
    re.IGNORECASE,
)
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_KNOWN_TECH_NAMES = (
    "Shopify",
    "WooCommerce",
    "Magento",
    "BigCommerce",
    "Wati",
    "Nudgify",
    "Fera",
    "Judge.me",
    "Loox",
    "Smile.io",
    "Klaviyo",
    "Easysize",
)


class AllowedClaim:
    """A field-level claim that has passed provenance validation and is safe for outreach."""

    def __init__(
        self,
        field: str,
        extracted_value: str,
        source_url: str,
        confidence: str,
        raw_excerpt: str,
        evidence_id: str = "",
    ) -> None:
        self.field = field
        self.extracted_value = extracted_value
        self.source_url = source_url
        self.confidence = confidence
        self.raw_excerpt = raw_excerpt
        self.evidence_id = evidence_id

    def __repr__(self) -> str:
        return (
            f"AllowedClaim(field={self.field!r}, "
            f"value={self.extracted_value!r}, "
            f"confidence={self.confidence!r})"
        )


class ClaimValidationResult:
    """Result of validating all claims for a single candidate."""

    def __init__(
        self,
        candidate_id: str,
        allowed_outreach_claims: List[AllowedClaim],
        blocked_fields: List[str],
        low_obs_labels: Dict[str, str],
    ) -> None:
        self.candidate_id = candidate_id
        self.allowed_outreach_claims = allowed_outreach_claims
        self.blocked_fields = blocked_fields
        self.low_obs_labels = low_obs_labels

    @property
    def has_any_allowed_claim(self) -> bool:
        return len(self.allowed_outreach_claims) > 0

    def to_summary(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "allowed_claims": [
                {
                    "field": c.field,
                    "extracted_value": c.extracted_value,
                    "source_url": c.source_url,
                    "confidence": c.confidence,
                    "evidence_id": c.evidence_id,
                }
                for c in self.allowed_outreach_claims
            ],
            "blocked_fields": self.blocked_fields,
            "low_obs_labels": self.low_obs_labels,
        }


def _excerpt_supports_value(extracted_value: str, raw_excerpt: str, signal_type: str = "") -> bool:
    """Verify that the raw_excerpt or signal_type genuinely anchors the extracted_value."""
    if not raw_excerpt or not extracted_value:
        return False
    combined = f"{raw_excerpt} {signal_type}".lower()
    tokens = [t.strip().lower() for t in re.split(r"[,/|]+", extracted_value) if t.strip()]
    if not tokens:
        return False
    for tok in tokens:
        if tok in combined:
            return True
        base = tok.split(".")[0]
        if len(base) >= 3 and base in combined:
            return True
    return False


class MayaClaimValidator:
    """Builds the allowed_outreach_claims whitelist from Evidence provenance checks."""

    def __init__(
        self,
        session: ResearchSession,
        db_path: Optional[str] = None,
    ) -> None:
        self.session = session
        self._db_path = db_path

    @property
    def db_path(self) -> str:
        return self._db_path or _conn_mod.DB_PATH

    def validate(self, candidate_id: str) -> ClaimValidationResult:
        """Validate and return the allowed outreach claims for a candidate."""
        evidence_rows = self._load_evidence(candidate_id)

        allowed: Dict[str, AllowedClaim] = {}
        blocked_fields: List[str] = []
        low_obs_labels: Dict[str, str] = dict(_LOW_OBS_LABELS)

        # Check for conflicting platform evidence on this candidate
        platform_vals = {
            (e.get("extracted_value") or "").strip().lower()
            for e in evidence_rows
            if e.get("supports_field") == "platform" and e.get("confidence") in OUTREACH_CONFIDENT_LEVELS
        }
        platform_vals.discard("")
        platform_contradicted = len(platform_vals) > 1

        for ev in evidence_rows:
            field = ev.get("supports_field", "unknown")
            if field == "apps":
                field = "installed_apps"
            confidence = ev.get("confidence", "LOW")
            raw_excerpt = (ev.get("raw_excerpt") or "").strip()
            extracted_value = (ev.get("extracted_value") or "").strip()
            source_url = (ev.get("source_url") or "").strip()
            source_type = (ev.get("source_type") or "").strip()
            signal_type = (ev.get("signal_type") or "").strip()
            ev_id = (ev.get("id") or "").strip()

            if field == "platform" and platform_contradicted:
                if field not in blocked_fields:
                    blocked_fields.append(field)
                continue

            if field == "storefront_state" and extracted_value.lower() != "active":
                if field not in blocked_fields:
                    blocked_fields.append(field)
                continue

            if field in LOW_OBSERVABILITY_FIELDS:
                if source_type not in AUTHORITATIVE_FINANCIAL_SOURCES:
                    low_obs_labels[field] = _LOW_OBS_LABELS.get(
                        field, f"UNVERIFIED ({field} not publicly observable)"
                    )
                    if field not in blocked_fields:
                        blocked_fields.append(field)
                    continue

            if confidence not in OUTREACH_CONFIDENT_LEVELS:
                if field not in blocked_fields:
                    blocked_fields.append(field)
                continue

            if not raw_excerpt or not extracted_value:
                if field not in blocked_fields:
                    blocked_fields.append(field)
                continue

            if not _excerpt_supports_value(extracted_value, raw_excerpt, signal_type):
                if field not in blocked_fields:
                    blocked_fields.append(field)
                continue

            if field not in allowed or (
                confidence == "HIGH" and allowed[field].confidence != "HIGH"
            ):
                allowed[field] = AllowedClaim(
                    field=field,
                    extracted_value=extracted_value,
                    source_url=source_url,
                    confidence=confidence,
                    raw_excerpt=raw_excerpt,
                    evidence_id=ev_id,
                )

        blocked_fields = [f for f in blocked_fields if f not in allowed]

        logger.info(
            "[ClaimValidator][session=%s] candidate=%s: %d allowed, %d blocked, %d low_obs",
            self.session.id,
            candidate_id,
            len(allowed),
            len(blocked_fields),
            len(low_obs_labels),
        )

        return ClaimValidationResult(
            candidate_id=candidate_id,
            allowed_outreach_claims=list(allowed.values()),
            blocked_fields=blocked_fields,
            low_obs_labels=low_obs_labels,
        )

    def validate_batch(
        self, candidate_ids: List[str]
    ) -> Dict[str, ClaimValidationResult]:
        return {cid: self.validate(cid) for cid in candidate_ids}

    @classmethod
    def validate_outreach_against_whitelist(
        cls,
        text: str,
        validation_result: ClaimValidationResult,
    ) -> Tuple[bool, List[str]]:
        """Verify that drafted outreach text contains zero claims outside `allowed_outreach_claims`.

        Returns `(is_valid, violations)`.
        """
        if not text:
            return True, []

        violations: List[str] = []
        allowed_by_field = {c.field: c.extracted_value for c in validation_result.allowed_outreach_claims}
        allowed_values_blob = " ".join(c.extracted_value.lower() for c in validation_result.allowed_outreach_claims)

        if "performance_audit" not in allowed_by_field:
            if _UNMEASURED_SPEED_PATTERN.search(text):
                violations.append("Hallucinated page load speed (performance_audit is NOT_AUDITED)")
            if _BOUNCE_RATE_PATTERN.search(text):
                violations.append("Hallucinated bounce rate / cart abandonment (performance_audit is NOT_AUDITED)")

        if "paid_app_subscription" not in allowed_by_field:
            if _PAID_APP_CLAIM_PATTERN.search(text):
                violations.append("Upgraded installed_apps to paid_app_subscription without billing evidence")

        if "revenue" not in allowed_by_field:
            if _REVENUE_CLAIM_PATTERN.search(text):
                violations.append("Hallucinated private revenue/turnover figure (revenue is UNVERIFIED)")

        if "contact" not in allowed_by_field:
            emails = _EMAIL_PATTERN.findall(text)
            if emails:
                violations.append(f"Fabricated contact email(s) not in evidence: {emails}")

        # Check for any mentioned platform or app name that is not in the candidate's allowed claims
        for tech in _KNOWN_TECH_NAMES:
            if re.search(rf"\b{re.escape(tech)}\b", text, re.IGNORECASE):
                if tech.lower() not in allowed_values_blob:
                    violations.append(f"Claimed unverified technology/app '{tech}' not in allowed_outreach_claims")

        return len(violations) == 0, violations

    @staticmethod
    def validate_and_repair_text(
        text: str,
        validation_result: Optional[ClaimValidationResult] = None,
    ) -> Tuple[str, bool, List[str]]:
        """Post-composition check that strips hallucinated speed, bounce, paid-tier, or revenue claims."""
        if not text:
            return text, False, []

        repaired = text
        violations: List[str] = []
        allowed_fields = (
            {c.field for c in validation_result.allowed_outreach_claims}
            if validation_result is not None
            else set()
        )

        if "performance_audit" not in allowed_fields:
            if _UNMEASURED_SPEED_PATTERN.search(repaired):
                violations.append("Rejected unmeasured load-time claim (performance_audit is NOT_AUDITED)")
                repaired = re.sub(
                    r"(?:takes?\s+(?:over\s+)?|loads?\s+in\s+|at\s+)\d+(?:\.\d+)?\s*(?:seconds?|secs?|s)\s*(?:to\s+load|on\s+mobile|load\s+time)?",
                    "has opportunities for mobile storefront optimization",
                    repaired,
                    flags=re.IGNORECASE,
                )

            if _BOUNCE_RATE_PATTERN.search(repaired):
                violations.append("Rejected unmeasured bounce-rate claim (performance_audit is NOT_AUDITED)")
                repaired = _BOUNCE_RATE_PATTERN.sub("potential checkout drop-off", repaired)

        if "paid_app_subscription" not in allowed_fields and _PAID_APP_CLAIM_PATTERN.search(repaired):
            violations.append("Rejected unverified paid_app_subscription claim")
            repaired = _PAID_APP_CLAIM_PATTERN.sub("installed third-party app", repaired)

        if "revenue" not in allowed_fields and _REVENUE_CLAIM_PATTERN.search(repaired):
            violations.append("Rejected unverified private revenue figure")
            repaired = _REVENUE_CLAIM_PATTERN.sub("[UNVERIFIED REVENUE]", repaired)

        return repaired, len(violations) > 0, violations

    def _load_evidence(self, candidate_id: str) -> List[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, session_id, candidate_id, source_url, source_type,
                       supports_field, signal_type, extracted_value, raw_excerpt, confidence
                FROM evidence WHERE candidate_id=? AND session_id=?
                """,
                (candidate_id, self.session.id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
