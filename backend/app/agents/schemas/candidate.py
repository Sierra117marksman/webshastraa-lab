from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from app.agents.schemas.claim import Claim


QualificationStatus = Literal["VERIFIED", "PROSPECT", "REJECTED", "PENDING"]


class Candidate(BaseModel):
    """
    Persistent record in the CandidateLedger.
    Tracks field-specific verification state rather than a single boolean flag.
    """
    id: str = Field(..., description="Unique candidate ID, e.g., 'C1'")
    company_name: str
    canonical_domain: str
    url: str
    discovered_from: str = ""
    discovery_hop: int = 1
    snippet_context: str = ""
    audited_by_verifier: bool = False

    # 8 Explicit Field-Specific Claims (Amendment #3)
    identity: Claim = Field(default_factory=lambda: Claim(field="identity", status="UNVERIFIED"))
    website: Claim = Field(default_factory=lambda: Claim(field="website", status="UNVERIFIED"))
    platform: Claim = Field(default_factory=lambda: Claim(field="platform", status="UNVERIFIED"))
    apps: Claim = Field(default_factory=lambda: Claim(field="apps", status="UNVERIFIED"))
    d2c_status: Claim = Field(default_factory=lambda: Claim(field="d2c_status", status="UNVERIFIED"))
    revenue: Claim = Field(default_factory=lambda: Claim(field="revenue", value="UNVERIFIED (Private entity)", status="UNVERIFIED"))
    website_condition: Claim = Field(
        default_factory=lambda: Claim(field="website_condition", value="NOT AUDITED (Requires speed test)", status="NOT_AUDITED")
    )
    contact: Claim = Field(default_factory=lambda: Claim(field="contact", status="UNVERIFIED"))

    # Qualification outcome
    qualification_status: QualificationStatus = "PENDING"
    qualification_reasons: List[str] = Field(default_factory=list)
    failed_checks: List[str] = Field(default_factory=list)
    confidence: float = 0.5

    def get_all_claims(self) -> Dict[str, Claim]:
        return {
            "identity": self.identity,
            "website": self.website,
            "platform": self.platform,
            "apps": self.apps,
            "d2c_status": self.d2c_status,
            "revenue": self.revenue,
            "website_condition": self.website_condition,
            "contact": self.contact,
        }

    def get_supported_claims(self) -> List[Claim]:
        """Returns ONLY claims with status == 'SUPPORTED' and non-empty evidence_ids."""
        return [
            c for c in self.get_all_claims().values()
            if c.status == "SUPPORTED" and len(c.evidence_ids) > 0 and c.value
        ]

    def get_missing_fields(self, required_fields: List[str]) -> List[str]:
        claims = self.get_all_claims()
        return [
            f for f in required_fields
            if f in claims and claims[f].status not in ("SUPPORTED",)
        ]


class CandidateLedger(BaseModel):
    """
    Stateful database of all candidates discovered across research hops.
    Prevents duplicate domain audits and tracks viable vs rejected candidates.
    """
    candidates: Dict[str, Candidate] = Field(default_factory=dict)
    domain_index: Dict[str, str] = Field(default_factory=dict)  # canonical_domain -> candidate_id
    _counter: int = 0

    def upsert_candidate(
        self,
        company_name: str,
        canonical_domain: str,
        url: str,
        discovered_from: str,
        discovery_hop: int,
        snippet_context: str = ""
    ) -> Optional[Candidate]:
        dom = canonical_domain.lower().strip()
        if not dom:
            return None

        if dom in self.domain_index:
            existing_id = self.domain_index[dom]
            existing = self.candidates[existing_id]
            if snippet_context and snippet_context not in existing.snippet_context:
                existing.snippet_context = (existing.snippet_context + " | " + snippet_context)[:1000]
            return existing

        self._counter += 1
        cid = f"C{self._counter}"
        cand = Candidate(
            id=cid,
            company_name=company_name.strip() or dom,
            canonical_domain=dom,
            url=url,
            discovered_from=discovered_from,
            discovery_hop=discovery_hop,
            snippet_context=snippet_context[:1000]
        )
        self.candidates[cid] = cand
        self.domain_index[dom] = cid
        return cand

    def get_unaudited(self, limit: int = 20) -> List[Candidate]:
        return [c for c in self.candidates.values() if not c.audited_by_verifier][:limit]

    @staticmethod
    def _rank_key(c: Candidate) -> tuple:
        has_apps = 1 if c.apps.status == "SUPPORTED" else 0
        not_password_page = 0 if c.url.rstrip("/").endswith("/password") else 1
        ev_count = len(c.all_evidence_ids())
        return (has_apps, not_password_page, ev_count)

    def get_viable(self) -> List[Candidate]:
        """Returns candidates qualified as VERIFIED or PROSPECT, ranked by evidence strength."""
        verified = sorted(
            [c for c in self.candidates.values() if c.qualification_status == "VERIFIED"],
            key=self._rank_key,
            reverse=True
        )
        prospects = sorted(
            [c for c in self.candidates.values() if c.qualification_status == "PROSPECT"],
            key=self._rank_key,
            reverse=True
        )
        return verified + prospects

    def get_verified(self) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.qualification_status == "VERIFIED"]

    def get_prospects(self) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.qualification_status == "PROSPECT"]

    def get_rejected(self) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.qualification_status == "REJECTED"]
