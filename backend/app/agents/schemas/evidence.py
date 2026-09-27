from datetime import datetime
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


SourceType = Literal[
    "live_http_headers",
    "live_html_footprint",
    "storeleads_directory",
    "search_snippet",
    "job_board",
    "company_page"
]


class Evidence(BaseModel):
    """
    First-class immutable evidence record stored in the EvidenceStore.
    Every supported claim on a Candidate must reference one or more Evidence IDs.
    """
    id: str = Field(..., description="Unique evidence ID, e.g., 'E1', 'E2'")
    candidate_id: str = Field(..., description="ID of the candidate this evidence relates to")
    source_url: str = Field(..., description="Primary URL where this evidence was observed")
    source_type: SourceType = Field(..., description="How this evidence was collected")
    supports_field: str = Field(
        ...,
        description="Which Candidate field this evidence supports (e.g., 'platform', 'apps', 'd2c_status')"
    )
    supports_claim: str = Field(..., description="Specific factual value supported, e.g., 'Shopify' or 'Judge.me'")
    content_excerpt: str = Field(..., description="Raw snippet or mechanical fingerprint proving the claim")
    retrieved_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EvidenceStore(BaseModel):
    """
    Central repository of all Evidence collected during a ResearchSession.
    Provides deterministic lookup so ClaimValidator can verify whether a Claim
    is genuinely backed by primary evidence.
    """
    items: Dict[str, Evidence] = Field(default_factory=dict)
    _counter: int = 0

    def add_evidence(
        self,
        candidate_id: str,
        source_url: str,
        source_type: SourceType,
        supports_field: str,
        supports_claim: str,
        content_excerpt: str,
        confidence: float = 1.0
    ) -> Evidence:
        self._counter += 1
        ev_id = f"E{self._counter}"
        ev = Evidence(
            id=ev_id,
            candidate_id=candidate_id,
            source_url=source_url,
            source_type=source_type,
            supports_field=supports_field,
            supports_claim=supports_claim,
            content_excerpt=content_excerpt[:500],
            confidence=confidence
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
