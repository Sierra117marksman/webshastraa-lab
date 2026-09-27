from typing import Any, Dict, List, Literal
from pydantic import BaseModel, Field


SessionStatus = Literal[
    "discovering",
    "collecting",
    "verifying",
    "qualifying",
    "composing",
    "validating",
    "completed",
    "exhausted"
]


class ResearchSession(BaseModel):
    """
    Explicit stateful ResearchSession owned by the Python State Machine.
    The LLM never decides when research is exhausted — Python evaluates termination
    rules against this object.
    """
    id: str
    task_id: str
    raw_prompt: str

    # Structured constraints parsed by Planner
    hard_constraints: Dict[str, Any] = Field(default_factory=dict)
    soft_constraints: Dict[str, Any] = Field(default_factory=dict)
    target_leads: int = 10

    # Explicit budget & termination limits (Amendment #5)
    current_hop: int = 0
    max_hops: int = 4
    max_candidates: int = 50
    max_verification_requests: int = 50

    # Live counters
    candidates_found: int = 0
    candidates_verified: int = 0
    verification_requests_made: int = 0

    # History & deduplication
    search_queries_used: List[str] = Field(default_factory=list)
    domains_seen: List[str] = Field(default_factory=list)

    # Measured Telemetry (Amendment #1: measure actual LLM/tool usage)
    llm_calls_made: int = 0
    tavily_calls_made: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    status: SessionStatus = "discovering"
    termination_reason: str = ""

    def should_continue_discovery(self, viable_count: int) -> bool:
        """
        Deterministic termination check owned by Python (never the LLM):
        - If viable_count >= target_leads -> Stop discovery, go to COMPOSE
        - Else if current_hop >= max_hops -> Exhausted, go to COMPOSE
        - Else if candidates_found >= max_candidates -> Exhausted, go to COMPOSE
        - Else if verification_requests_made >= max_verification_requests -> Exhausted, go to COMPOSE
        - Otherwise -> Continue to next hop in DISCOVER
        """
        if viable_count >= self.target_leads:
            self.termination_reason = f"Target met ({viable_count}/{self.target_leads} viable leads found)."
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
