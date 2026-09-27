"""Typed ResearchSession schema with forward-only hop transitions and locked approval resume."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set
from pydantic import BaseModel, Field, model_validator

from app.agents.schemas.requirement import Requirement


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SessionStatus = Literal[
    "planning",
    "discovering",
    "collecting",
    "verifying",
    "qualifying",
    "composing",
    "validating",
    "waiting_approval",
    "completed",
    "exhausted",
    "failed",
    "needs_clarification",
    "rejected",
]

ResumeState = Literal[
    "discovering",
    "collecting",
    "verifying",
    "qualifying",
    "composing",
    "validating",
    "completed",
]

VALID_RESUME_STATES: Set[str] = {
    "discovering",
    "collecting",
    "verifying",
    "qualifying",
    "composing",
    "validating",
    "completed",
}

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "planning": {"discovering", "needs_clarification", "failed"},
    "discovering": {"collecting", "exhausted", "failed"},
    "collecting": {"verifying", "failed"},
    "verifying": {"qualifying", "failed"},
    "qualifying": {"composing", "discovering", "exhausted", "failed"},
    "composing": {"validating", "failed"},
    "validating": {"completed", "waiting_approval", "composing", "failed"},
    "waiting_approval": {"rejected", "failed"},  # Approval exit exclusively via resume_from_approval(task)
    "exhausted": {"composing", "completed", "failed"},
    "needs_clarification": {"planning", "failed"},
    "completed": {"waiting_approval"},
    "failed": set(),
    "rejected": set(),
}


class InvalidStateTransitionError(RuntimeError):
    """Raised when a caller attempts an illegal ResearchSession state transition."""


class ResearchSession(BaseModel):
    """Explicit stateful ResearchSession owned by the Python control plane."""
    id: str
    task_id: str
    employee_id: str = "emp_sdr_01"
    raw_prompt: str

    # Typed requirements (v2) + legacy dicts for transitional compatibility
    requirements: List[Requirement] = Field(default_factory=list)
    hard_constraints: Dict[str, Any] = Field(default_factory=dict)
    soft_constraints: Dict[str, Any] = Field(default_factory=dict)

    target_verified_leads: int = Field(default=10, ge=1)
    allow_prospects: bool = True

    # Explicit budget & termination limits
    current_hop: int = Field(default=0, ge=0)
    max_hops: int = Field(default=4, ge=1)
    max_candidates: int = Field(default=50, ge=1)
    max_verification_requests: int = Field(default=50, ge=1)

    # Live counters
    candidates_found: int = Field(default=0, ge=0)
    candidates_verified: int = Field(default=0, ge=0)
    verification_requests_made: int = Field(default=0, ge=0)

    # History & deduplication
    search_queries_used: List[str] = Field(default_factory=list)
    domains_seen: List[str] = Field(default_factory=list)

    # Measured Telemetry
    llm_calls_made: int = Field(default=0, ge=0)
    tavily_calls_made: int = Field(default=0, ge=0)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)

    status: SessionStatus = "planning"
    termination_reason: Optional[str] = ""
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)

    @model_validator(mode="before")
    @classmethod
    def _sync_target_leads(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if "target_leads" in data and "target_verified_leads" not in data:
            data["target_verified_leads"] = data.pop("target_leads")
        elif "target_leads" in data:
            data.pop("target_leads")
        return data

    @property
    def target_leads(self) -> int:
        return self.target_verified_leads

    @target_leads.setter
    def target_leads(self, val: int) -> None:
        self.target_verified_leads = val

    def transition_to(self, next_state: SessionStatus) -> SessionStatus:
        """Enforce ALLOWED_TRANSITIONS and forward-only hop budget."""
        allowed = ALLOWED_TRANSITIONS.get(self.status, set())
        if next_state not in allowed:
            raise InvalidStateTransitionError(
                f"Illegal session transition '{self.status}' -> '{next_state}'. "
                f"Allowed from '{self.status}': {sorted(allowed)}"
            )

        if next_state == "discovering":
            next_hop = self.current_hop + 1
            if next_hop > self.max_hops:
                raise InvalidStateTransitionError(
                    f"Cannot enter 'discovering' at hop {next_hop}: exceeds max_hops={self.max_hops}"
                )
            self.current_hop = next_hop

        self.status = next_state
        self.updated_at = _utc_now()
        return self.status

    def resume_from_approval(self, task: Any) -> SessionStatus:
        """Locked approval resume per Rev 3 Section 4.3.

        Caller cannot pass a destination state; destination is read strictly
        from `task.resume_state`.
        """
        if self.status != "waiting_approval":
            raise InvalidStateTransitionError(
                f"Cannot resume session in status '{self.status}' (must be 'waiting_approval')"
            )
        resume_state = getattr(task, "resume_state", None)
        if not resume_state and isinstance(task, dict):
            resume_state = task.get("resume_state")
        if not resume_state:
            raise InvalidStateTransitionError("Task has no recorded resume_state")
        if resume_state not in VALID_RESUME_STATES:
            raise InvalidStateTransitionError(f"Task has invalid resume_state '{resume_state}'")

        self.status = resume_state  # type: ignore[assignment]
        self.updated_at = _utc_now()
        return self.status

    def should_continue_discovery(self, viable_count: int) -> bool:
        """Deterministic termination check owned by Python (never the LLM)."""
        if viable_count >= self.target_verified_leads:
            self.termination_reason = f"Target met ({viable_count}/{self.target_verified_leads} viable leads found)."
            return False
        if self.current_hop >= self.max_hops:
            self.status = "exhausted"
            self.termination_reason = (
                f"Search budget exhausted after {self.current_hop}/{self.max_hops} hops "
                f"({viable_count} viable leads survived verification)."
            )
            return False
        if self.candidates_found >= self.max_candidates:
            self.status = "exhausted"
            self.termination_reason = f"Candidate cap reached ({self.candidates_found}/{self.max_candidates})."
            return False
        if self.verification_requests_made >= self.max_verification_requests:
            self.status = "exhausted"
            self.termination_reason = (
                f"Verification request cap reached ({self.verification_requests_made}/{self.max_verification_requests})."
            )
            return False
        return True
