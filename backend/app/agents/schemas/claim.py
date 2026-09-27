from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


ClaimStatus = Literal["SUPPORTED", "UNVERIFIED", "NOT_AUDITED", "CONTRADICTED"]


class Claim(BaseModel):
    """
    Field-specific claim on a Candidate.
    Cannot be marked SUPPORTED unless backed by at least one Evidence ID in the EvidenceStore.
    """
    field: str = Field(..., description="Field name, e.g., 'platform', 'apps', 'revenue', 'website_condition'")
    value: Optional[str] = Field(default=None, description="Claimed value, e.g., 'Shopify' or 'Wati, Judge.me'")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of Evidence objects supporting this claim")
    status: ClaimStatus = Field(default="UNVERIFIED")
    notes: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def enforce_evidence_for_supported(self) -> "Claim":
        if self.status == "SUPPORTED" and not self.evidence_ids:
            self.status = "UNVERIFIED"
            self.notes = "Downgraded from SUPPORTED to UNVERIFIED: no evidence_ids attached."
        return self
