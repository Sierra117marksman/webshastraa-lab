"""Typed Candidate and CandidateLedger schemas for Maya v2."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from app.agents.schemas.claim import Claim, QualificationDecision


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


QualificationStatus = Literal["PENDING", "VERIFIED", "PROSPECT", "REJECTED"]

StorefrontState = Literal[
    "active",
    "password_locked",
    "maintenance",
    "dead",
    "unknown",
]


class Candidate(BaseModel):
    """Persistent candidate record synchronized with `latest_decision_id`."""
    id: str = Field(..., description="Unique candidate ID, e.g., 'C1'")
    session_id: str = Field(default="sess_default")
    company_name: str
    canonical_domain: str
    initial_url: str = ""
    final_url: Optional[str] = None
    discovered_from_url: str = ""
    discovery_hop: int = 1
    snippet_context: str = ""

    # Mechanical HTTP & Storefront state
    http_reachable: Optional[bool] = None
    http_status: Optional[int] = None
    page_available: Optional[bool] = None
    storefront_state: StorefrontState = "unknown"
    audited_by_verifier: bool = False

    # Field-specific Claims (v2 schema separating installed_apps vs paid_app_subscription
    # and technical_observables vs performance_audit)
    identity: Claim = Field(default_factory=lambda: Claim(field="identity", status="UNVERIFIED"))
    website: Claim = Field(default_factory=lambda: Claim(field="website", status="UNVERIFIED"))
    platform: Claim = Field(default_factory=lambda: Claim(field="platform", status="UNVERIFIED"))
    installed_apps: Claim = Field(default_factory=lambda: Claim(field="installed_apps", status="UNVERIFIED"))
    paid_app_subscription: Claim = Field(
        default_factory=lambda: Claim(
            field="paid_app_subscription",
            value="UNVERIFIED (Billing tier not publicly observable)",
            status="UNVERIFIED",
        )
    )
    d2c_status: Claim = Field(default_factory=lambda: Claim(field="d2c_status", status="UNVERIFIED"))
    revenue: Claim = Field(
        default_factory=lambda: Claim(
            field="revenue",
            value="UNVERIFIED (Private entity)",
            status="UNVERIFIED",
        )
    )
    technical_observables: Claim = Field(
        default_factory=lambda: Claim(field="technical_observables", status="UNVERIFIED")
    )
    performance_audit: Claim = Field(
        default_factory=lambda: Claim(
            field="performance_audit",
            value="NOT AUDITED (Requires speed test)",
            status="NOT_AUDITED",
        )
    )
    contact: Claim = Field(default_factory=lambda: Claim(field="contact", status="UNVERIFIED"))

    # Materialized qualification status synchronized with latest_decision_id
    qualification_status: QualificationStatus = "PENDING"
    latest_decision_id: Optional[str] = None
    qualification_reasons: List[str] = Field(default_factory=list)
    failed_checks: List[str] = Field(default_factory=list)
    confidence: float = 0.5
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if not data.get("initial_url") and data.get("url"):
            data["initial_url"] = data.pop("url")
        elif "url" in data:
            data.pop("url")

        if not data.get("discovered_from_url") and "discovered_from" in data:
            data["discovered_from_url"] = data.pop("discovered_from")
        elif "discovered_from" in data:
            data.pop("discovered_from")

        if "apps" in data and "installed_apps" not in data:
            data["installed_apps"] = data.pop("apps")
        if "website_condition" in data and "performance_audit" not in data:
            data["performance_audit"] = data.pop("website_condition")

        return data

    @property
    def url(self) -> str:
        return self.final_url or self.initial_url

    @url.setter
    def url(self, val: str) -> None:
        self.initial_url = val

    @property
    def discovered_from(self) -> str:
        return self.discovered_from_url

    @discovered_from.setter
    def discovered_from(self, val: str) -> None:
        self.discovered_from_url = val

    @property
    def apps(self) -> Claim:
        return self.installed_apps

    @apps.setter
    def apps(self, val: Claim) -> None:
        self.installed_apps = val

    @property
    def website_condition(self) -> Claim:
        return self.performance_audit

    @website_condition.setter
    def website_condition(self, val: Claim) -> None:
        self.performance_audit = val

    def apply_qualification_decision(self, decision: QualificationDecision) -> None:
        """Synchronize candidate's materialized qualification_status with a QualificationDecision."""
        if decision.candidate_id != self.id:
            raise ValueError(
                f"QualificationDecision candidate_id '{decision.candidate_id}' does not match Candidate '{self.id}'"
            )
        self.latest_decision_id = decision.id
        self.qualification_status = decision.result
        self.qualification_reasons = list(decision.notes)
        self.updated_at = decision.decided_at

    def get_all_claims(self) -> Dict[str, Claim]:
        claims: Dict[str, Claim] = {
            "identity": self.identity,
            "website": self.website,
            "platform": self.platform,
            "installed_apps": self.installed_apps,
            "paid_app_subscription": self.paid_app_subscription,
            "d2c_status": self.d2c_status,
            "revenue": self.revenue,
            "technical_observables": self.technical_observables,
            "performance_audit": self.performance_audit,
            "contact": self.contact,
        }
        # Expose legacy alias keys when a claim uses the legacy field name
        if self.installed_apps.field == "apps":
            claims["apps"] = self.installed_apps
        if self.performance_audit.field == "website_condition":
            claims["website_condition"] = self.performance_audit
        return claims

    def all_evidence_ids(self) -> List[str]:
        seen: List[str] = []
        for claim in self.get_all_claims().values():
            for eid in claim.evidence_ids:
                if eid not in seen:
                    seen.append(eid)
        return seen

    def get_supported_claims(self) -> List[Claim]:
        """Returns ONLY claims with status == 'SUPPORTED' and non-empty evidence_ids."""
        unique_claims = {
            id(c): c
            for c in self.get_all_claims().values()
            if c.status == "SUPPORTED" and len(c.evidence_ids) > 0 and c.value
        }
        return list(unique_claims.values())

    def get_missing_fields(self, required_fields: List[str]) -> List[str]:
        claims = self.get_all_claims()
        return [
            f for f in required_fields
            if f in claims and claims[f].status not in ("SUPPORTED",)
        ]


class CandidateLedger(BaseModel):
    """Stateful ledger of all candidates discovered across research hops."""
    candidates: Dict[str, Candidate] = Field(default_factory=dict)
    domain_index: Dict[str, str] = Field(default_factory=dict)
    _counter: int = 0

    def upsert_candidate(
        self,
        company_name: str,
        canonical_domain: str,
        url: str,
        discovered_from: str,
        discovery_hop: int,
        snippet_context: str = "",
        session_id: str = "sess_default",
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
            session_id=session_id,
            company_name=company_name.strip() or dom,
            canonical_domain=dom,
            initial_url=url,
            discovered_from_url=discovered_from,
            discovery_hop=discovery_hop,
            snippet_context=snippet_context[:1000],
        )
        self.candidates[cid] = cand
        self.domain_index[dom] = cid
        return cand

    def get_unaudited(self, limit: int = 20) -> List[Candidate]:
        return [c for c in self.candidates.values() if not c.audited_by_verifier][:limit]

    @staticmethod
    def _rank_key(c: Candidate) -> tuple:
        has_apps = 1 if c.installed_apps.status == "SUPPORTED" else 0
        not_password_page = 0 if (c.storefront_state == "password_locked" or c.url.rstrip("/").endswith("/password")) else 1
        ev_count = len(c.all_evidence_ids())
        return (has_apps, not_password_page, ev_count)

    def get_viable(self) -> List[Candidate]:
        verified = sorted(
            [c for c in self.candidates.values() if c.qualification_status == "VERIFIED"],
            key=self._rank_key,
            reverse=True,
        )
        prospects = sorted(
            [c for c in self.candidates.values() if c.qualification_status == "PROSPECT"],
            key=self._rank_key,
            reverse=True,
        )
        return verified + prospects

    def get_verified(self) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.qualification_status == "VERIFIED"]

    def get_prospects(self) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.qualification_status == "PROSPECT"]

    def get_rejected(self) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.qualification_status == "REJECTED"]
