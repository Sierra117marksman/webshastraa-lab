"""Typed Requirement schema for Maya v2 research sessions."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Sequence, Union
import uuid
from pydantic import BaseModel, Field, model_validator


RequirementField = Literal[
    "platform",
    "installed_apps",
    "paid_app_subscription",
    "d2c_status",
    "revenue",
    "technical_observables",
    "performance_audit",
    "geography",
    "storefront_state",
    "contact",
    "hiring_role",
]

RequirementOperator = Literal[
    "equals",
    "in",
    "contains_any",
    "range",
    "exists",
]

RequirementPriority = Literal["HARD", "SOFT"]
UnknownPolicy = Literal["REJECT", "PROSPECT"]
ObservabilityClass = Literal["HIGH", "MEDIUM", "LOW_PUBLIC_OBSERVABILITY"]

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


class NumericRange(BaseModel):
    """Typed range constraint for numeric requirements such as annual turnover."""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    currency: Optional[str] = None
    unit: Optional[str] = None


ExpectedValue = Union[str, int, float, bool, List[str], NumericRange]


DEFAULT_ALLOWED_SOURCES: Dict[RequirementField, List[SourceType]] = {
    "platform": ["live_http_headers", "live_html_footprint", "storeleads_directory"],
    "installed_apps": ["live_html_footprint", "storeleads_directory"],
    "paid_app_subscription": ["official_company_page", "annual_filing", "official_financial_report"],
    "d2c_status": ["live_html_footprint", "official_company_page", "storeleads_directory"],
    "revenue": ["official_company_page", "annual_filing", "official_financial_report"],
    "technical_observables": ["live_http_headers", "live_html_footprint"],
    "performance_audit": ["official_company_page"],
    "geography": ["live_html_footprint", "storeleads_directory", "official_company_page", "search_snippet"],
    "storefront_state": ["live_http_headers", "live_html_footprint"],
    "contact": ["live_html_footprint", "official_company_page", "job_board"],
    "hiring_role": ["job_board", "official_company_page", "search_snippet"],
}

LOW_OBSERVABILITY_FIELDS: set[RequirementField] = {
    "revenue",
    "paid_app_subscription",
    "performance_audit",
}

AUTHORITATIVE_FINANCIAL_SOURCES: set[SourceType] = {
    "official_company_page",
    "annual_filing",
    "official_financial_report",
}


class Requirement(BaseModel):
    """Explicit, typed requirement evaluated by QualificationEngine.

    Separates high-observability signals (`installed_apps`, `technical_observables`)
    from inherently low-public-observability signals (`paid_app_subscription`,
    `revenue`, `performance_audit`).
    """
    id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:10]}")
    session_id: Optional[str] = None
    field: RequirementField
    operator: RequirementOperator = "equals"
    expected: ExpectedValue
    priority: RequirementPriority = "HARD"
    on_unknown: UnknownPolicy = "REJECT"
    observability_class: ObservabilityClass = "HIGH"
    evidence_required: bool = True
    allowed_source_types: List[SourceType] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_observability_and_source_invariants(self) -> "Requirement":
        if not self.allowed_source_types:
            self.allowed_source_types = list(DEFAULT_ALLOWED_SOURCES.get(self.field, ["official_company_page"]))

        # Low-public-observability fields cannot be verified from HTML footprints or search snippets
        # and must classify unknown private entities as PROSPECT rather than fabricating or hard-rejecting.
        if self.field in ("revenue", "paid_app_subscription"):
            self.observability_class = "LOW_PUBLIC_OBSERVABILITY"
            self.on_unknown = "PROSPECT"
            filtered = [s for s in self.allowed_source_types if s in AUTHORITATIVE_FINANCIAL_SOURCES]
            self.allowed_source_types = filtered or list(DEFAULT_ALLOWED_SOURCES[self.field])
        elif self.field == "performance_audit":
            self.observability_class = "LOW_PUBLIC_OBSERVABILITY"
            self.on_unknown = "PROSPECT"

        return self
