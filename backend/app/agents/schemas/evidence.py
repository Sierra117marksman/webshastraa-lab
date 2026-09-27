"""Immutable Evidence, VerificationEvidence, and EvidenceStore schemas for Maya v2."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SourceType = Literal[
    "live_http_headers",
    "live_html_footprint",
    "storeleads_directory",
    "annual_filing",
    "official_financial_report",
    "official_company_page",
    "job_board",
    "search_snippet",
]

ConfidenceLevel = Literal["HIGH", "MEDIUM", "LOW"]


def compute_evidence_content_hash(
    candidate_id: str,
    source_url: str,
    source_type: str,
    supports_field: str,
    signal_type: str,
    extracted_value: str,
    raw_excerpt: str,
) -> str:
    payload = (
        f"{candidate_id.strip()}|{source_url.strip()}|{source_type.strip()}|"
        f"{supports_field.strip()}|{signal_type.strip()}|{extracted_value.strip()}|{raw_excerpt.strip()}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_confidence(val: Union[str, float, int, None]) -> ConfidenceLevel:
    if isinstance(val, str):
        upper = val.strip().upper()
        if upper in ("HIGH", "MEDIUM", "LOW"):
            return upper  # type: ignore[return-value]
    if isinstance(val, (int, float)):
        if val >= 0.8:
            return "HIGH"
        if val >= 0.5:
            return "MEDIUM"
        return "LOW"
    return "HIGH"


class VerificationEvidence(BaseModel):
    """Mechanical observation emitted by DomainVerificationService before candidate binding."""
    verifier_version: str = "v2.0"
    source_url: str
    source_type: SourceType
    supports_field: str
    signal_type: str
    extracted_value: str
    raw_excerpt: str
    confidence: ConfidenceLevel = "HIGH"
    content_hash: str = ""
    retrieved_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="before")
    @classmethod
    def _coerce_verification_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if data.get("source_type") == "company_page":
            data["source_type"] = "official_company_page"
        data["confidence"] = _normalize_confidence(data.get("confidence", "HIGH"))
        if not data.get("content_hash"):
            data["content_hash"] = compute_evidence_content_hash(
                candidate_id=str(data.get("candidate_id", "")),
                source_url=str(data.get("source_url", "")),
                source_type=str(data.get("source_type", "")),
                supports_field=str(data.get("supports_field", "")),
                signal_type=str(data.get("signal_type", "")),
                extracted_value=str(data.get("extracted_value", "")),
                raw_excerpt=str(data.get("raw_excerpt", "")),
            )
        return data


class Evidence(BaseModel):
    """First-class immutable evidence record stored in the append-only `evidence` table."""
    id: str = Field(..., description="Unique evidence ID, e.g., 'E1', 'E2'")
    session_id: str = Field(default="sess_default", description="ResearchSession ID")
    candidate_id: str = Field(..., description="Candidate ID this evidence belongs to")
    verifier_version: str = Field(default="v2.0")
    source_url: str = Field(..., description="Primary URL where this evidence was observed")
    source_type: SourceType = Field(..., description="Mechanical or authoritative source category")
    supports_field: str = Field(..., description="Candidate field supported by this observation")
    signal_type: str = Field(default="mechanical_footprint", description="Specific signal type, e.g., 'header:x-shopid'")
    extracted_value: str = Field(..., description="Canonical extracted value, e.g., 'Shopify' or 'Judge.me'")
    raw_excerpt: str = Field(..., description="Bounded raw excerpt proving the observation")
    content_hash: str = Field(default="", description="SHA-256 content hash for deduplication and tamper detection")
    confidence: ConfidenceLevel = Field(default="HIGH")
    financial_period: Optional[str] = Field(default=None)
    retrieved_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_and_hash(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if "extracted_value" not in data and "supports_claim" in data:
            data["extracted_value"] = data.pop("supports_claim")
        elif "supports_claim" in data:
            data.pop("supports_claim")

        if "raw_excerpt" not in data and "content_excerpt" in data:
            data["raw_excerpt"] = data.pop("content_excerpt")
        elif "content_excerpt" in data:
            data.pop("content_excerpt")

        if data.get("source_type") == "company_page":
            data["source_type"] = "official_company_page"

        data["confidence"] = _normalize_confidence(data.get("confidence", "HIGH"))
        raw_excerpt = str(data.get("raw_excerpt", ""))[:500]
        data["raw_excerpt"] = raw_excerpt

        if not data.get("content_hash"):
            data["content_hash"] = compute_evidence_content_hash(
                candidate_id=str(data.get("candidate_id", "")),
                source_url=str(data.get("source_url", "")),
                source_type=str(data.get("source_type", "")),
                supports_field=str(data.get("supports_field", "")),
                signal_type=str(data.get("signal_type", "mechanical_footprint")),
                extracted_value=str(data.get("extracted_value", "")),
                raw_excerpt=raw_excerpt,
            )
        return data

    @property
    def supports_claim(self) -> str:
        """Backward-compatible alias for `extracted_value`."""
        return self.extracted_value

    @property
    def content_excerpt(self) -> str:
        """Backward-compatible alias for `raw_excerpt`."""
        return self.raw_excerpt


class EvidenceStore(BaseModel):
    """In-memory and session-scoped lookup over immutable Evidence records."""
    items: Dict[str, Evidence] = Field(default_factory=dict)
    _counter: int = 0

    def add_evidence(
        self,
        candidate_id: str,
        source_url: str,
        source_type: str,
        supports_field: str,
        supports_claim: Optional[str] = None,
        content_excerpt: Optional[str] = None,
        confidence: Union[ConfidenceLevel, float] = "HIGH",
        *,
        session_id: str = "sess_default",
        verifier_version: str = "v2.0",
        signal_type: str = "mechanical_footprint",
        extracted_value: Optional[str] = None,
        raw_excerpt: Optional[str] = None,
        financial_period: Optional[str] = None,
    ) -> Evidence:
        self._counter += 1
        ev_id = f"E{self._counter}"
        final_value = extracted_value if extracted_value is not None else (supports_claim or "")
        final_excerpt = raw_excerpt if raw_excerpt is not None else (content_excerpt or "")
        ev = Evidence(
            id=ev_id,
            session_id=session_id,
            candidate_id=candidate_id,
            verifier_version=verifier_version,
            source_url=source_url,
            source_type=source_type,  # type: ignore[arg-type]
            supports_field=supports_field,
            signal_type=signal_type,
            extracted_value=final_value,
            raw_excerpt=final_excerpt[:500],
            confidence=_normalize_confidence(confidence),
            financial_period=financial_period,
        )
        self.items[ev_id] = ev
        return ev

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self.items.get(evidence_id)

    def get_for_candidate(self, candidate_id: str) -> List[Evidence]:
        return [ev for ev in self.items.values() if ev.candidate_id == candidate_id]

    def get_for_field(self, candidate_id: str, field_name: str) -> List[Evidence]:
        return [
            ev for ev in self.items.values()
            if ev.candidate_id == candidate_id and ev.supports_field == field_name
        ]
