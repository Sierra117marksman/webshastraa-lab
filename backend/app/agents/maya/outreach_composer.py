"""Maya OutreachComposer — generates deliverable strictly from allowed_outreach_claims.

Outreach integrity invariants (Rev 3):
1. NEVER fabricates contact emails — uses only ClaimValidationResult.allowed_outreach_claims
2. NEVER states unmeasured performance numbers — raw_excerpt must anchor every metric claim
3. LOW_PUBLIC_OBSERVABILITY fields (revenue, paid_app_subscription, performance_audit) always use their UNVERIFIED/NOT AUDITED label
4. The LLM draft is generated strictly from the allowed claims whitelist as context, never from raw evidence
5. If the LLM invents any claim outside `allowed_outreach_claims`, `MayaClaimValidator.validate_outreach_against_whitelist`
   rejects the LLM draft and replaces it with the deterministic whitelist-only template.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.agents.maya.claim_validator import ClaimValidationResult, MayaClaimValidator
from app.engine.llm_gateway import LLMGateway, LLMGatewayError

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a B2B outreach specialist writing honest, evidence-anchored cold outreach.

STRICT RULES — violations will be rejected:
1. Use ONLY the verified claims provided in the prompt. Never fabricate metrics, emails, or company details.
2. Never invent performance numbers (e.g. "your site loads in 4.8s" is FORBIDDEN unless from evidence).
3. If a field shows "UNVERIFIED" or "NOT AUDITED", reproduce that label exactly — do not invent a value.
4. Never generate a contact email unless the evidence provides one explicitly.
5. Write a personalized 3-sentence cold email pitch (To: field blank, Subject, Body) using only verified facts.
6. Format the final output as a structured JSON object matching the schema.
"""


class _OutreachSchema(BaseModel):
    """Structured outreach output schema."""
    company_overview: str = Field(default="")
    verified_signals: List[str] = Field(default_factory=list)
    outreach_subject: str = Field(default="")
    outreach_body: str = Field(default="")


class OutreachResult:
    """Composed outreach deliverable for a single candidate."""

    def __init__(
        self,
        candidate_id: str,
        company_name: str,
        canonical_domain: str,
        qualification_result: str,
        company_overview: str,
        verified_signals: List[str],
        outreach_subject: str,
        outreach_body: str,
        allowed_claim_count: int,
        low_obs_labels: Dict[str, str],
        rejected_llm_claims: Optional[List[str]] = None,
        allowed_claims: Optional[Dict[str, str]] = None,
    ) -> None:
        self.candidate_id = candidate_id
        self.company_name = company_name
        self.canonical_domain = canonical_domain
        self.qualification_result = qualification_result
        self.company_overview = company_overview
        self.verified_signals = verified_signals
        self.outreach_subject = outreach_subject
        self.outreach_body = outreach_body
        self.allowed_claim_count = allowed_claim_count
        self.low_obs_labels = low_obs_labels
        self.rejected_llm_claims = rejected_llm_claims or []
        self.allowed_claims: Dict[str, str] = allowed_claims or {}

    @property
    def subject(self) -> str:
        return self.outreach_subject

    @property
    def body(self) -> str:
        return self.outreach_body

    def to_markdown(self) -> str:
        signals_md = "\n".join(f"- {s}" for s in self.verified_signals) or "- No verified signals found"
        obs_labels_md = "\n".join(
            f"- **{k}**: {v}" for k, v in self.low_obs_labels.items()
        ) if self.low_obs_labels else ""

        return f"""## {self.company_name} ({self.canonical_domain})

**Qualification:** {self.qualification_result}

### Company Overview
{self.company_overview or '_Not available from verified evidence._'}

### Verified Signals
{signals_md}

{f"### Low-Observability / Unaudited Fields{chr(10)}{obs_labels_md}{chr(10)}" if obs_labels_md else ""}
### Cold Outreach Draft
**Subject:** {self.outreach_subject or '(subject not generated)'}

{self.outreach_body or '_Outreach draft not generated — insufficient verified evidence._'}
"""


def _deterministic_outreach_template(
    company_name: str,
    canonical_domain: str,
    allowed_map: Dict[str, str],
) -> tuple[str, str, str]:
    """Build a consultative, zero-hallucination cold email strictly from allowed claims."""
    platform = allowed_map.get("platform", "ecommerce")
    apps = allowed_map.get("installed_apps") or allowed_map.get("apps")
    overview = f"{company_name} operates a {platform} storefront at {canonical_domain}."
    subject = f"Quick question on {company_name}'s {platform} storefront"
    if apps:
        body = (
            f"Hi {company_name} Team,\n\n"
            f"I was reviewing your {platform} storefront at {canonical_domain} and noticed you are running "
            f"third-party apps including {apps}.\n\n"
            f"While we haven't run a formal speed audit on {canonical_domain} yet, multiple injected app scripts "
            f"often create opportunities for mobile storefront optimization. Open to a quick 60-second teardown?"
        )
    else:
        body = (
            f"Hi {company_name} Team,\n\n"
            f"I was exploring your {platform} storefront at {canonical_domain}.\n\n"
            f"While we haven't audited your internal performance metrics yet, I'd love to share a quick "
            f"3-point storefront architecture review tailored to {company_name}."
        )
    return overview, subject, body


class MayaOutreachComposer:
    """Generates structured outreach deliverables strictly from allowed_outreach_claims."""

    def __init__(self, gateway: Optional[LLMGateway] = None) -> None:
        self._gateway = gateway or LLMGateway()

    def compose(
        self,
        validation_result: ClaimValidationResult,
        company_name: str,
        canonical_domain: str,
        qualification_result: str,
        task_prompt: str = "",
    ) -> OutreachResult:
        """Generate outreach for a single candidate strictly from its allowed claims whitelist."""
        candidate_id = validation_result.candidate_id
        allowed = validation_result.allowed_outreach_claims
        low_obs = validation_result.low_obs_labels

        if not allowed:
            logger.info(
                "[OutreachComposer] candidate=%s has no allowed claims — minimal output",
                candidate_id,
            )
            return OutreachResult(
                candidate_id=candidate_id,
                company_name=company_name,
                canonical_domain=canonical_domain,
                qualification_result=qualification_result,
                company_overview="Insufficient verified evidence for detailed overview.",
                verified_signals=[],
                outreach_subject="",
                outreach_body="",
                allowed_claim_count=0,
                low_obs_labels=low_obs,
            )

        allowed_map = {c.field: c.extracted_value for c in allowed}
        default_overview, default_subject, default_body = _deterministic_outreach_template(
            company_name, canonical_domain, allowed_map
        )
        default_signals = [f"{c.field}: {c.extracted_value} ({c.source_url})" for c in allowed]

        claims_text = "\n".join(
            f"- Field: {c.field} | Value: {c.extracted_value} | Source: {c.source_url} | Confidence: {c.confidence}"
            f"\n  Evidence excerpt: \"{c.raw_excerpt[:300]}\""
            for c in allowed
        )
        low_obs_text = "\n".join(f"- {k}: {v}" for k, v in low_obs.items()) if low_obs else "None"

        user_prompt = f"""\
Company: {company_name}
Domain: {canonical_domain}
Qualification: {qualification_result}
Task context: {task_prompt[:300] if task_prompt else 'B2B lead outreach'}

VERIFIED CLAIMS (use ONLY these):
{claims_text}

UNVERIFIABLE FIELDS (reproduce exact label, never invent a value):
{low_obs_text}

Generate the structured outreach report.
"""

        try:
            llm_result = self._gateway.call(
                contents=[{"role": "user", "content": user_prompt}],
                system_prompt=SYSTEM_PROMPT,
                response_schema=_OutreachSchema,
            )
            parsed: Optional[_OutreachSchema] = llm_result.parsed_result  # type: ignore[assignment]
        except LLMGatewayError as exc:
            logger.warning("[OutreachComposer] LLMGateway failed for candidate=%s (%s) — using deterministic template", candidate_id, exc)
            parsed = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OutreachComposer] Unexpected error for candidate=%s (%s) — using deterministic template", candidate_id, exc)
            parsed = None

        if parsed is None:
            return OutreachResult(
                candidate_id=candidate_id,
                company_name=company_name,
                canonical_domain=canonical_domain,
                qualification_result=qualification_result,
                company_overview=default_overview,
                verified_signals=default_signals,
                outreach_subject=default_subject,
                outreach_body=default_body,
                allowed_claim_count=len(allowed),
                low_obs_labels=low_obs,
                allowed_claims=allowed_map,
            )

        combined_llm_text = "\n".join(
            filter(None, [parsed.company_overview, parsed.outreach_subject, parsed.outreach_body] + list(parsed.verified_signals or []))
        )
        is_valid, violations = MayaClaimValidator.validate_outreach_against_whitelist(
            combined_llm_text, validation_result
        )
        if not is_valid:
            logger.warning(
                "[OutreachComposer] Rejected hallucinated LLM outreach claims for %s: %s — falling back to deterministic whitelist template",
                candidate_id,
                violations,
            )
            return OutreachResult(
                candidate_id=candidate_id,
                company_name=company_name,
                canonical_domain=canonical_domain,
                qualification_result=qualification_result,
                company_overview=default_overview,
                verified_signals=default_signals,
                outreach_subject=default_subject,
                outreach_body=default_body,
                allowed_claim_count=len(allowed),
                low_obs_labels=low_obs,
                rejected_llm_claims=violations,
                allowed_claims=allowed_map,
            )

        repaired_body, _, _ = MayaClaimValidator.validate_and_repair_text(
            parsed.outreach_body or default_body, validation_result
        )
        repaired_overview, _, _ = MayaClaimValidator.validate_and_repair_text(
            parsed.company_overview or default_overview, validation_result
        )

        return OutreachResult(
            candidate_id=candidate_id,
            company_name=company_name,
            canonical_domain=canonical_domain,
            qualification_result=qualification_result,
            company_overview=repaired_overview,
            verified_signals=parsed.verified_signals or default_signals,
            outreach_subject=parsed.outreach_subject or default_subject,
            outreach_body=repaired_body,
            allowed_claim_count=len(allowed),
            low_obs_labels=low_obs,
            allowed_claims=allowed_map,
        )

    def compose_deterministic(
        self,
        validation_result: ClaimValidationResult,
        company_name: str,
        canonical_domain: str,
        qualification_result: str,
    ) -> OutreachResult:
        """Fast deterministic composition from allowed claims whitelist without invoking LLM."""
        allowed = validation_result.allowed_outreach_claims
        allowed_map = {c.field: c.extracted_value for c in allowed}
        default_overview, default_subject, default_body = _deterministic_outreach_template(
            company_name, canonical_domain, allowed_map
        )
        default_signals = [f"{c.field}: {c.extracted_value} ({c.source_url})" for c in allowed]
        return OutreachResult(
            candidate_id=validation_result.candidate_id,
            company_name=company_name,
            canonical_domain=canonical_domain,
            qualification_result=qualification_result,
            company_overview=default_overview,
            verified_signals=default_signals,
            outreach_subject=default_subject,
            outreach_body=default_body,
            allowed_claim_count=len(allowed),
            low_obs_labels=validation_result.low_obs_labels,
            allowed_claims=allowed_map,
        )

    def compose_batch(
        self,
        validations: List[ClaimValidationResult],
        candidate_meta: Dict[str, Dict[str, Any]],
        task_prompt: str = "",
    ) -> List[OutreachResult]:
        """Compose outreach for a list of candidates."""
        results: List[OutreachResult] = []
        for val in validations:
            meta = candidate_meta.get(val.candidate_id, {})
            results.append(
                self.compose(
                    validation_result=val,
                    company_name=meta.get("company_name", val.candidate_id),
                    canonical_domain=meta.get("canonical_domain", ""),
                    qualification_result=meta.get("qualification_result", "PROSPECT"),
                    task_prompt=task_prompt,
                )
            )
        return results
