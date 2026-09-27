"""
Memory, Permission, and Audit Log data models.

Design invariants:
- MemoryRecord categories NEVER include 'policy_override'.
  Policy changes are PolicyConfig records, not learned memory.
- AuditLogEntry is append-only — records are never mutated after write.
- ToolPermission is the source of truth for what each employee may do.
"""

from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ---------------------------------------------------------------------------
# Permission System
# ---------------------------------------------------------------------------

PermissionScope = Literal["READ", "ANALYZE", "DRAFT", "REQUEST", "EXECUTE"]

class ToolPermission(BaseModel):
    tool_id: str
    permission: PermissionScope
    requires_approval: bool
    notes: Optional[str] = None


# Default permission sets per seeded employee
SEEDED_PERMISSIONS: dict[str, list[ToolPermission]] = {
    "emp_sdr_01": [  # Maya Vance (CRM)
        ToolPermission(tool_id="web_search",    permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="sheet_logger",  permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="email_sender",  permission="REQUEST", requires_approval=True,
                       notes="Maya may draft and stage emails but not dispatch without approval."),
        ToolPermission(tool_id="slack_notifier", permission="EXECUTE", requires_approval=False),
    ],
    "emp_hr_01": [  # Arjun Patel (HRM)
        ToolPermission(tool_id="web_search",    permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="sheet_logger",  permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="email_sender",  permission="REQUEST", requires_approval=True,
                       notes="Interview invites require human review."),
    ],
    "emp_mkt_01": [  # Chloe Chen (Marketing)
        ToolPermission(tool_id="web_search",    permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="sheet_logger",  permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="email_sender",  permission="DRAFT",   requires_approval=True,
                       notes="Chloe may draft campaign emails only — never dispatch."),
        ToolPermission(tool_id="slack_notifier", permission="REQUEST", requires_approval=True,
                       notes="Campaign announcements to Slack need approval."),
    ],
    "emp_ops_01": [  # David Kim (Operations)
        ToolPermission(tool_id="web_search",    permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="sheet_logger",  permission="EXECUTE", requires_approval=False),
        ToolPermission(tool_id="email_sender",  permission="REQUEST", requires_approval=True,
                       notes="David may draft vendor hold notices — not dispatch without finance sign-off."),
        ToolPermission(tool_id="slack_notifier", permission="REQUEST", requires_approval=True,
                       notes="Finance escalation alerts need approval."),
    ],
}


# ---------------------------------------------------------------------------
# Memory Record
# ---------------------------------------------------------------------------

MemoryCategory = Literal[
    "mistake_avoided",    # Something the employee did wrong that was corrected
    "learned_rule",       # An operational rule extracted from founder feedback
    "proven_playbook",    # A pattern that has produced good outcomes repeatedly
    "founder_preference", # Explicit stylistic or strategic preference from founder
    # NOTE: 'policy_override' is intentionally excluded.
    # Policy changes are PolicyConfig records (a separate system).
    # Memory CANNOT represent or override policy.
]

MemoryScope = Literal[
    "global",
    "cold_outreach",
    "lead_research",
    "hiring_research",
    "enterprise_clients",
    "financial_ops",
    "content_creation",
]

VALID_MEMORY_SCOPES: tuple[str, ...] = (
    "global",
    "cold_outreach",
    "lead_research",
    "hiring_research",
    "enterprise_clients",
    "financial_ops",
    "content_creation",
)

SCOPE_ALIASES: dict[str, str] = {
    "follow_up_emails": "cold_outreach",
    "outreach": "cold_outreach",
    "email_outreach": "cold_outreach",
    "data_research": "lead_research",
    "research": "lead_research",
    "hiring": "hiring_research",
    "recruiting": "hiring_research",
    "enterprise": "enterprise_clients",
    "finance": "financial_ops",
    "billing": "financial_ops",
    "content": "content_creation",
    "marketing": "content_creation",
}

MemoryStage = Literal[
    "PLAN",
    "COLLECT",
    "VERIFY",
    "QUALIFY",
    "COMPOSE",
    "REFLECT",
]

VALID_MEMORY_STAGES: tuple[str, ...] = (
    "PLAN",
    "COLLECT",
    "VERIFY",
    "QUALIFY",
    "COMPOSE",
    "REFLECT",
)

MemoryTrigger = Literal[
    "rejection",          # Founder rejected an approval action
    "task_failure",       # Task ended in error or suboptimal result
    "manual_feedback",    # Founder wrote feedback on a completed task
    "positive_signoff",   # High-quality result — pattern worth preserving
    "founder_direct",     # Founder created the rule manually in Memory Vault UI
]

MemoryStatus = Literal[
    "proposed",    # Generated by reflection, awaiting founder review
    "active",      # Confirmed and injected into future task prompts
    "superseded",  # Replaced by a newer conflicting rule (preserved for audit)
    "rejected",    # Founder explicitly dismissed this proposed memory
]


def normalize_memory_scope(raw_scope: Optional[str]) -> str:
    """Normalize a scope string to one of the 7 v2 SQLite-enforced MemoryScope values."""
    if not raw_scope:
        return "global"
    cleaned = str(raw_scope).strip().lower().replace(" ", "_").replace("-", "_")
    if cleaned in VALID_MEMORY_SCOPES:
        return cleaned
    if cleaned in SCOPE_ALIASES:
        return SCOPE_ALIASES[cleaned]
    return "global"


def normalize_memory_stages(stages: Optional[List[str]]) -> List[MemoryStage]:
    """Normalize stage names to valid uppercase MemoryStage values, defaulting to ['PLAN', 'COMPOSE']."""
    if not stages:
        return ["PLAN", "COMPOSE"]
    normalized: List[MemoryStage] = []
    for s in stages:
        upper = str(s).strip().upper()
        if upper in VALID_MEMORY_STAGES and upper not in normalized:
            normalized.append(upper)  # type: ignore[arg-type]
    return normalized or ["PLAN", "COMPOSE"]


def compute_rule_key(category: str, scope: str, topic_or_title: str) -> str:
    """Compute a deterministic canonical rule_key for conflict detection and indexing."""
    import re
    norm_scope = normalize_memory_scope(scope)
    norm_topic = re.sub(r"[^a-z0-9]+", "_", (topic_or_title or "").strip().casefold()).strip("_")
    if not norm_topic:
        norm_topic = "general"
    return f"memory:{category}:{norm_scope}:{norm_topic}"


from pydantic import field_validator, model_validator


class MemoryRecord(BaseModel):
    id: str
    employee_id: str
    category: MemoryCategory
    title: str                        # Short label, e.g. "Max discount 10%"
    trigger_event: MemoryTrigger
    scope: str = "global"             # Normalized to VALID_MEMORY_SCOPES
    applies_to_stages: List[MemoryStage] = Field(default_factory=lambda: ["PLAN", "COMPOSE"])
    rule_key: Optional[str] = None    # Canonical key: memory:{category}:{scope}:{topic}
    source: str                       # e.g. "Founder feedback on task_a1b2c3d4"
    context: str                      # Brief summary of what triggered this learning
    critique: str                     # What went wrong or what was corrected
    distilled_rule: str               # Imperative instruction for the runner prompt
    confidence_score: float = Field(ge=0.0, le=1.0)
    priority: int = Field(default=3, ge=1, le=5)  # 1 = highest
    version: int = 1
    supersedes: Optional[str] = None  # ID of older conflicting rule this replaces
    status: MemoryStatus = "proposed"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_confirmed_at: Optional[str] = None
    activated_at: Optional[str] = None

    @field_validator("scope", mode="before")
    @classmethod
    def _validate_scope(cls, v: Optional[str]) -> str:
        return normalize_memory_scope(v)

    @field_validator("applies_to_stages", mode="before")
    @classmethod
    def _validate_stages(cls, v: Optional[List[str]]) -> List[MemoryStage]:
        return normalize_memory_stages(v)

    @model_validator(mode="after")
    def _ensure_rule_key(self) -> "MemoryRecord":
        if not self.rule_key or not str(self.rule_key).strip():
            self.rule_key = compute_rule_key(self.category, self.scope, self.title)
        return self


class CreateMemoryRequest(BaseModel):
    category: MemoryCategory
    title: str
    scope: str = "global"
    applies_to_stages: List[MemoryStage] = Field(default_factory=lambda: ["PLAN", "COMPOSE"])
    rule_key: Optional[str] = None
    context: str
    critique: str
    distilled_rule: str
    priority: int = 3
    trigger_event: MemoryTrigger = "founder_direct"


class UpdateMemoryRequest(BaseModel):
    title: Optional[str] = None
    distilled_rule: Optional[str] = None
    scope: Optional[str] = None
    applies_to_stages: Optional[List[MemoryStage]] = None
    priority: Optional[int] = None
    status: Optional[MemoryStatus] = None


# ---------------------------------------------------------------------------
# Activity & Audit Log
# ---------------------------------------------------------------------------

class AuditLogEntry(BaseModel):
    id: str
    employee_id: str
    task_id: str
    session_id: Optional[str] = None
    context_snapshot_id: Optional[str] = None
    event_type: Literal[
        "dispatch",
        "context_built",
        "policy_check_pass",
        "policy_check_block",
        "tool_call",
        "approval_request",
        "approval_granted",
        "approval_rejected",
        "memory_injected",
        "reflection_proposed",
        "memory_activated",
        "memory_superseded",
        "memory_rejected",
        "memory_conflict_resolved",
        "employee_compiled",
        "task_completed",
        "task_failed",
    ]
    prompt_version: Optional[str] = None   # SHA256 hash of compiled context snapshot
    memories_used: List[str] = Field(default_factory=list)  # Memory record IDs
    tools_called: List[str] = Field(default_factory=list)
    decision: Optional[str] = None
    output_summary: str = ""
    founder_feedback: Optional[str] = None
    final_action: Optional[str] = None
    cost_usd: float = 0.0
    tokens_used: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Founder Feedback Request
# ---------------------------------------------------------------------------

class TaskFeedbackRequest(BaseModel):
    feedback: str
    quality_rating: Optional[Literal["poor", "acceptable", "good", "excellent"]] = None
    auto_create_memory: bool = True  # Whether to pass feedback through reflection engine
