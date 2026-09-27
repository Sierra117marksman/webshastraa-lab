"""Mutable Claim and immutable QualificationDecision schemas for Maya v2."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Literal, Optional
import uuid
from pydantic import BaseModel, Field, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ClaimStatus = Literal[
    "SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTED",
    "UNVERIFIED",
    "NOT_AUDITED",
]

QualificationResult = Literal["VERIFIED", "PROSPECT", "REJECTED"]

RequirementEvalStatus = Literal[
    "SATISFIED",
    "UNVERIFIED",
    "CONTRADICTED",
    "NOT_AUDITED",
]


class Claim(BaseModel):
    """Mutable current field-level interpretation on a Candidate.

    Cannot be marked SUPPORTED unless backed by at least one Evidence ID.
    Whenever updated with new observations across hops, `version` increments.
    """
    id: str = Field(default_factory=lambda: f"clm_{uuid.uuid4().hex[:10]}")
    session_id: str = Field(default="sess_default")
    candidate_id: str = Field(default="cand_default")
    field: str = Field(..., description="Field name, e.g., 'platform', 'installed_apps', 'revenue'")
    value: Optional[str] = Field(default=None, description="Claimed value, e.g., 'Shopify' or 'Judge.me'")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of Evidence objects supporting this claim")
    status: ClaimStatus = Field(default="UNVERIFIED")
    notes: Optional[str] = Field(default=None)
    version: int = Field(default=1, ge=1)
    updated_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def enforce_evidence_for_supported(self) -> "Claim":
        if self.status == "SUPPORTED" and not self.evidence_ids:
            self.status = "UNVERIFIED"
            self.notes = "Downgraded from SUPPORTED to UNVERIFIED: no evidence_ids attached."
        return self

    def revise(
        self,
        *,
        value: Optional[str],
        status: ClaimStatus,
        evidence_ids: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> "Claim":
        """Mutate claim in-place and increment version counter per Rev 3 Section 4.1."""
        self.value = value
        self.evidence_ids = list(evidence_ids or [])
        self.status = status
        self.notes = notes
        if self.status == "SUPPORTED" and not self.evidence_ids:
            self.status = "UNVERIFIED"
            self.notes = "Downgraded from SUPPORTED to UNVERIFIED: no evidence_ids attached."
        self.version += 1
        self.updated_at = _utc_now()
        return self


class ClaimSnapshotItem(BaseModel):
    """Immutable snapshot of a single Claim captured inside a QualificationDecision."""
    claim_id: str
    field: str
    value: Optional[str] = None
    status: ClaimStatus
    version: int = 1
    evidence_ids: List[str] = Field(default_factory=list)


class RequirementEvaluation(BaseModel):
    """Typed per-requirement evaluation captured inside a QualificationDecision."""
    requirement_id: str
    field: str
    priority: Literal["HARD", "SOFT"] = "HARD"
    status: RequirementEvalStatus
    evidence_ids: List[str] = Field(default_factory=list)
    reason: str = ""


def _canonical_json(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    elif isinstance(obj, dict):
        obj = {k: (v.model_dump() if hasattr(v, "model_dump") else v) for k, v in obj.items()}
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_decision_hash(
    session_id: str,
    candidate_id: str,
    hop: int,
    result: QualificationResult,
    requirement_results: Dict[str, RequirementEvaluation],
    claims_snapshot: Dict[str, ClaimSnapshotItem],
    supporting_evidence_ids: List[str],
    engine_version: str = "v2.0",
) -> str:
    raw = (
        f"{session_id}|{candidate_id}|{hop}|{result}|"
        f"{_canonical_json(requirement_results)}|"
        f"{_canonical_json(claims_snapshot)}|"
        f"{','.join(sorted(set(supporting_evidence_ids)))}|{engine_version}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class QualificationDecision(BaseModel):
    """Immutable, idempotent historical verdict computed at QUALIFY stage for (session_id, candidate_id, hop)."""
    id: str = Field(default_factory=lambda: f"qd_{uuid.uuid4().hex[:10]}")
    session_id: str
    candidate_id: str
    hop: int = Field(ge=1)
    result: QualificationResult
    decision_hash: str = ""
    claims_snapshot: Dict[str, ClaimSnapshotItem] = Field(default_factory=dict)
    requirement_results: Dict[str, RequirementEvaluation] = Field(default_factory=dict)
    supporting_claim_ids: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    engine_version: str = "v2.0"
    notes: List[str] = Field(default_factory=list)
    decided_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def ensure_decision_hash(self) -> "QualificationDecision":
        self.supporting_claim_ids = sorted(set(self.supporting_claim_ids))
        self.supporting_evidence_ids = sorted(set(self.supporting_evidence_ids))
        if not self.decision_hash:
            self.decision_hash = compute_decision_hash(
                session_id=self.session_id,
                candidate_id=self.candidate_id,
                hop=self.hop,
                result=self.result,
                requirement_results=self.requirement_results,
                claims_snapshot=self.claims_snapshot,
                supporting_evidence_ids=self.supporting_evidence_ids,
                engine_version=self.engine_version,
            )
        return self

    @property
    def claims_snapshot_json(self) -> str:
        return _canonical_json(self.claims_snapshot)

    @property
    def requirement_results_json(self) -> str:
        return _canonical_json(self.requirement_results)

    @property
    def supporting_claim_ids_json(self) -> str:
        return json.dumps(self.supporting_claim_ids, ensure_ascii=False)

    @property
    def supporting_evidence_ids_json(self) -> str:
        return json.dumps(self.supporting_evidence_ids, ensure_ascii=False)

    @property
    def notes_json(self) -> str:
        return json.dumps(self.notes, ensure_ascii=False)
