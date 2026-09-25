"""
Policy & Guardrail Engine — Phase 1

This is a STATELESS enforcement layer. It does not learn.
It enforces what each employee is ALLOWED to do.

Separation of concerns:
  - Memory tells the employee what it has LEARNED.
  - Policy tells the employee what it is ALLOWED TO DO.
  - These are separate systems and must never collapse into each other.
"""

from __future__ import annotations
import os
import re
import uuid
from datetime import datetime
from typing import Optional

from app.models.memory import ToolPermission, AuditLogEntry
from app.db.store import get_permission, save_audit_log


# Hard-coded organizational guardrails that can never be overridden by memory.
# These are loaded from env/config and enforced unconditionally.
def _load_blacklisted_domains() -> list[str]:
    raw = os.getenv("BLACKLIST_DOMAINS", "investor.com,board.com,vip.com,internal.com")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


class PolicyViolation(Exception):
    """Raised when an employee attempts an action that violates policy."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class PolicyCheckResult:
    def __init__(self, allowed: bool, reason: str, requires_approval: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.requires_approval = requires_approval


def check_tool_permission(
    employee_id: str,
    tool_name: str,
    tool_params: Optional[dict],
    task_id: str,
) -> PolicyCheckResult:
    """
    Check whether an employee is allowed to call a given tool.

    Returns a PolicyCheckResult:
      - allowed=True, requires_approval=False  → execute immediately
      - allowed=True, requires_approval=True   → route to approval gate
      - allowed=False                          → block and log

    Always writes an audit log entry regardless of outcome.
    """
    normalized = (tool_name or "").lower().replace(" ", "_").strip()

    # 1. Resolve the permission record for this employee+tool
    perm: Optional[ToolPermission] = get_permission(employee_id, normalized)

    if perm is None:
        # Tool not in employee's toolbelt at all — hard block
        result = PolicyCheckResult(
            allowed=False,
            reason=f"Tool '{normalized}' is not registered in this employee's toolbelt.",
        )
        _log_policy_event(employee_id, task_id, "policy_check_block", result.reason)
        return result

    # 2. READ and ANALYZE never produce external side-effects
    if perm.permission in ("READ", "ANALYZE"):
        result = PolicyCheckResult(
            allowed=False,
            reason=f"Employee permission level '{perm.permission}' does not permit executing '{normalized}'.",
        )
        _log_policy_event(employee_id, task_id, "policy_check_block", result.reason)
        return result

    # 3. DRAFT = may generate content but never dispatch externally
    if perm.permission == "DRAFT" and normalized in ("email_sender", "slack_notifier"):
        result = PolicyCheckResult(
            allowed=False,
            reason=f"DRAFT permission: '{normalized}' may be composed but not dispatched. "
                   f"Escalate to founder approval.",
        )
        _log_policy_event(employee_id, task_id, "policy_check_block", result.reason)
        return result

    # 4. REQUEST → allowed but must go through approval gate
    if perm.permission == "REQUEST" or perm.requires_approval:
        # Domain blacklist check for emails before routing to approval
        if normalized == "email_sender" and tool_params:
            to_addr = (tool_params.get("to") or "").lower()
            blocked = _load_blacklisted_domains()
            for domain in blocked:
                if domain in to_addr:
                    result = PolicyCheckResult(
                        allowed=False,
                        reason=f"Hard block: recipient domain '{domain}' is on the organization blacklist.",
                    )
                    _log_policy_event(employee_id, task_id, "policy_check_block", result.reason)
                    return result

        result = PolicyCheckResult(
            allowed=True,
            reason=f"Tool '{normalized}' requires founder approval before execution.",
            requires_approval=True,
        )
        _log_policy_event(employee_id, task_id, "policy_check_pass", result.reason)
        return result

    # 5. EXECUTE and no approval required → check domain blacklist for emails then allow
    if normalized == "email_sender" and tool_params:
        to_addr = (tool_params.get("to") or "").lower()
        blocked = _load_blacklisted_domains()
        for domain in blocked:
            if domain in to_addr:
                result = PolicyCheckResult(
                    allowed=False,
                    reason=f"Hard block: recipient domain '{domain}' is on the organization blacklist.",
                )
                _log_policy_event(employee_id, task_id, "policy_check_block", result.reason)
                return result

    result = PolicyCheckResult(
        allowed=True,
        reason=f"Permission check passed for '{normalized}' (level: {perm.permission}).",
        requires_approval=False,
    )
    _log_policy_event(employee_id, task_id, "policy_check_pass", result.reason)
    return result


def _log_policy_event(employee_id: str, task_id: str, event_type: str, decision: str):
    """Write a policy check audit log entry."""
    entry = AuditLogEntry(
        id=f"audit_{uuid.uuid4().hex[:12]}",
        employee_id=employee_id,
        task_id=task_id,
        event_type=event_type,  # type: ignore[arg-type]
        decision=decision,
        output_summary=decision,
        timestamp=datetime.utcnow().isoformat(),
    )
    try:
        save_audit_log(entry)
    except Exception:
        pass  # Audit log failure must never crash the execution pipeline
