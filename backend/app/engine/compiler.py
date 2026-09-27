"""
Meta-Agent Employee Compiler — Phase 4 (Maya v2 Frozen Contract)

Key Architectural Invariant:
  - The LLM proposes an employee specification (`EmployeeProposalSchema`) via `LLMGateway`.
  - Python validates the proposal and resolves tool permissions **fail-closed**.
  - External side-effect tools (`email_sender`, `slack_notifier`) can NEVER receive
    unapproved `EXECUTE` permission from an LLM proposal, even if the LLM returns
    `requires_approval_for=[]`.
  - Unknown or hallucinated tool IDs are stripped before the spec or SQLite `permissions`
    rows are created.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from app.db.connection import DB_PATH, transaction
from app.db.store import save_audit_log, save_employee, save_permission
from app.engine.llm_gateway import LLMGateway
from app.models.employee import AIEmployeeSpec
from app.models.memory import AuditLogEntry, ToolPermission

KNOWN_TOOLS: Tuple[str, ...] = (
    "web_search",
    "sheet_logger",
    "email_sender",
    "slack_notifier",
)

EXTERNAL_SIDE_EFFECT_TOOLS: frozenset[str] = frozenset({"email_sender", "slack_notifier"})

VALID_DEPARTMENTS: Tuple[str, ...] = ("Marketing", "HRM", "CRM", "Operations")
VALID_THEME_COLORS: Tuple[str, ...] = ("blue", "purple", "emerald", "amber", "rose", "indigo")
VALID_SCHEDULES: Tuple[str, ...] = ("on_demand", "daily", "interval")


COMPILER_SYSTEM_INSTRUCTION = """You are the Meta-Agent Architect for an autonomous AI Employee platform.
Take a founder's plain-English prompt and propose a structured Autonomous AI Employee specification.

Rules:
- name: Realistic professional human name (e.g. 'Elena Rostova', 'Marcus Vance')
- role: Clear job title (e.g. 'Outbound B2B SDR', 'Technical Recruiting Screener')
- department: Exactly one of: 'Marketing', 'HRM', 'CRM', 'Operations'
- avatar_emoji: Single fitting emoji (e.g. 🎯, 🚀, 📋, ⚡, 🔍, 📊)
- theme_color: Exactly one of: 'blue', 'purple', 'emerald', 'amber', 'rose', 'indigo'
- objective: Outcome-oriented 1-2 sentence mission statement
- persona: Tone, communication style, and behavioral traits
- sops: 3-5 concrete step-by-step Standard Operating Procedures
- tools: Subset of ['web_search', 'email_sender', 'sheet_logger', 'slack_notifier']
- schedule_type: One of: 'on_demand', 'daily', 'interval'
- schedule_interval_mins: Integer or null
- requires_approval_for: Subset of tools requiring human sign-off

Return ONLY valid JSON matching the requested schema."""


class EmployeeProposalSchema(BaseModel):
    name: str = Field(default="AI Specialist")
    role: str = Field(default="Autonomous Agent")
    department: str = Field(default="Operations")
    avatar_emoji: str = Field(default="🤖")
    theme_color: str = Field(default="blue")
    objective: str = Field(default="")
    persona: str = Field(default="Thorough, analytical, and execution-oriented.")
    sops: List[str] = Field(
        default_factory=lambda: [
            "1. Analyze objective.",
            "2. Execute actions.",
            "3. Report results.",
        ]
    )
    tools: List[str] = Field(default_factory=lambda: ["web_search", "sheet_logger"])
    schedule_type: str = Field(default="on_demand")
    schedule_interval_mins: Optional[int] = None
    requires_approval_for: List[str] = Field(default_factory=lambda: ["email_sender"])


def resolve_fail_closed_permissions(
    proposed_tools: List[str],
    proposed_requires_approval_for: Optional[List[str]] = None,
    *,
    department: str = "Operations",
) -> Tuple[List[str], List[str], List[ToolPermission]]:
    """
    Deterministically resolve tool permissions fail-closed in Python.

    Invariants:
      1. Unknown tool IDs not in KNOWN_TOOLS are stripped.
      2. If no valid tools remain, default to ['web_search', 'sheet_logger'].
      3. External side-effect tools ('email_sender', 'slack_notifier') ALWAYS require
         human approval (`requires_approval=True`) and receive at most `REQUEST` (or
         `DRAFT` for Marketing email_sender), regardless of what the LLM proposed.
      4. Internal tools ('web_search', 'sheet_logger') receive `EXECUTE` unless the
         proposal explicitly placed them in `requires_approval_for`, in which case
         they are downgraded to `REQUEST` with `requires_approval=True`.
    """
    normalized_tools: List[str] = []
    for raw_tool in proposed_tools or []:
        t = str(raw_tool).strip().lower().replace(" ", "_")
        if t in KNOWN_TOOLS and t not in normalized_tools:
            normalized_tools.append(t)

    if not normalized_tools:
        normalized_tools = ["web_search", "sheet_logger"]

    requested_approval_set = {
        str(t).strip().lower().replace(" ", "_")
        for t in (proposed_requires_approval_for or [])
        if str(t).strip()
    }

    resolved_approval_tools: List[str] = []
    resolved_permissions: List[ToolPermission] = []

    for tool_id in normalized_tools:
        if tool_id in EXTERNAL_SIDE_EFFECT_TOOLS:
            # Fail-closed: LLM can never grant unapproved EXECUTE on external side-effect tools
            resolved_approval_tools.append(tool_id)
            if department == "Marketing" and tool_id == "email_sender":
                resolved_permissions.append(
                    ToolPermission(
                        tool_id=tool_id,
                        permission="DRAFT",
                        requires_approval=True,
                        notes="Fail-closed compiler policy: Marketing may draft emails only; dispatch requires approval.",
                    )
                )
            else:
                resolved_permissions.append(
                    ToolPermission(
                        tool_id=tool_id,
                        permission="REQUEST",
                        requires_approval=True,
                        notes=f"Fail-closed compiler policy: '{tool_id}' always requires founder approval.",
                    )
                )
        elif tool_id in requested_approval_set:
            resolved_approval_tools.append(tool_id)
            resolved_permissions.append(
                ToolPermission(
                    tool_id=tool_id,
                    permission="REQUEST",
                    requires_approval=True,
                    notes=f"Approval requested for '{tool_id}' during compilation.",
                )
            )
        else:
            resolved_permissions.append(
                ToolPermission(
                    tool_id=tool_id,
                    permission="EXECUTE",
                    requires_approval=False,
                    notes=f"Safe internal execution permitted for '{tool_id}'.",
                )
            )

    return normalized_tools, resolved_approval_tools, resolved_permissions


def register_compiled_employee(
    spec: AIEmployeeSpec,
    permissions: Optional[List[ToolPermission]] = None,
) -> List[ToolPermission]:
    """
    Persist a compiled AIEmployeeSpec and its fail-closed ToolPermission rows
    into SQLite as the single authorization source of truth.
    """
    if permissions is None:
        clean_tools, clean_approval, permissions = resolve_fail_closed_permissions(
            spec.tools,
            spec.requires_approval_for,
            department=spec.department,
        )
        spec.tools = clean_tools
        spec.requires_approval_for = clean_approval

    save_employee(spec)
    for perm in permissions:
        save_permission(spec.id, perm)

    try:
        save_audit_log(
            AuditLogEntry(
                id=f"audit_{uuid.uuid4().hex[:12]}",
                employee_id=spec.id,
                task_id=f"compile_{spec.id}",
                event_type="employee_compiled",
                tools_called=[p.tool_id for p in permissions],
                decision=f"Registered fail-closed permissions for {spec.name} ({spec.id}).",
                output_summary=", ".join(
                    f"{p.tool_id}:{p.permission}(approval={p.requires_approval})"
                    for p in permissions
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )
    except Exception:
        pass

    return permissions


def compile_prompt_to_employee(
    user_prompt: str,
    *,
    gateway: Optional[LLMGateway] = None,
    persist: bool = False,
) -> AIEmployeeSpec:
    """
    Compile a founder's plain-English prompt into an AIEmployeeSpec via LLMGateway,
    enforcing fail-closed permission resolution in Python.
    """
    llm = gateway or LLMGateway()
    call_result = llm.call(
        contents=[{"role": "user", "content": f"Founder Prompt: {user_prompt}"}],
        system_prompt=COMPILER_SYSTEM_INSTRUCTION,
        response_schema=EmployeeProposalSchema,
    )

    if call_result.parsed_result is None:
        raise RuntimeError("Employee compilation failed: No structured proposal returned by LLMGateway")

    proposal: EmployeeProposalSchema = call_result.parsed_result

    department = proposal.department if proposal.department in VALID_DEPARTMENTS else "Operations"
    theme_color = proposal.theme_color if proposal.theme_color in VALID_THEME_COLORS else "blue"
    schedule_type = proposal.schedule_type if proposal.schedule_type in VALID_SCHEDULES else "on_demand"
    sops = [s.strip() for s in (proposal.sops or []) if str(s).strip()]
    if not sops:
        sops = ["1. Analyze objective.", "2. Execute actions.", "3. Report results."]

    clean_tools, clean_approval, resolved_permissions = resolve_fail_closed_permissions(
        proposal.tools,
        proposal.requires_approval_for,
        department=department,
    )

    employee_id = f"emp_{uuid.uuid4().hex[:8]}"
    spec = AIEmployeeSpec(
        id=employee_id,
        name=(proposal.name or "AI Specialist").strip(),
        role=(proposal.role or "Autonomous Agent").strip(),
        department=department,  # type: ignore[arg-type]
        avatar_emoji=(proposal.avatar_emoji or "🤖").strip() or "🤖",
        theme_color=theme_color,
        objective=(proposal.objective or user_prompt).strip(),
        persona=(proposal.persona or "Thorough, analytical, and execution-oriented.").strip(),
        sops=sops,
        tools=clean_tools,
        schedule_type=schedule_type,  # type: ignore[arg-type]
        schedule_interval_mins=proposal.schedule_interval_mins if schedule_type == "interval" else None,
        requires_approval_for=clean_approval,
    )

    if persist:
        register_compiled_employee(spec, resolved_permissions)

    return spec
