"""
Policy & Guardrail Engine — Phase 4 (Maya v2 Frozen Contract)

This is a STATELESS enforcement layer. It does not learn.
It enforces what each employee is ALLOWED to do using the SQLite `permissions`
table as the single source of truth for authorization.

Separation of concerns:
  - Memory tells the employee what it has LEARNED.
  - Policy tells the employee what it is ALLOWED TO DO.
  - EmployeeSpec fields (`tools`, `requires_approval_for`) are never consulted
    for runtime authorization; only `permissions` table rows govern access.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.store import get_permission, list_permissions, save_audit_log
from app.models.memory import AuditLogEntry, ToolPermission


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_blacklisted_domains() -> List[str]:
    raw = os.getenv("BLACKLIST_DOMAINS", "investor.com,board.com,vip.com,internal.com")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _extract_recipient_Blocked_domain(to_addr: str, blocked_domains: List[str]) -> Optional[str]:
    cleaned = (to_addr or "").strip().lower()
    if not cleaned:
        return None
    host = cleaned.rsplit("@", 1)[-1].strip("<> ") if "@" in cleaned else cleaned
    for domain in blocked_domains:
        if host == domain or host.endswith(f".{domain}") or domain in cleaned:
            return domain
    return None


class PolicyViolation(Exception):
    """Raised when an employee attempts an action that violates policy."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class PolicyCheckResult:
    def __init__(
        self,
        allowed: bool,
        reason: str,
        requires_approval: bool = False,
        permission_level: Optional[str] = None,
    ):
        self.allowed = allowed
        self.reason = reason
        self.requires_approval = requires_approval
        self.permission_level = permission_level


class PolicyEngine:
    """Authoritative runtime policy evaluator backed strictly by SQLite `permissions`."""

    @staticmethod
    def check_tool_permission(
        employee_id: str,
        tool_name: str,
        tool_params: Optional[Dict[str, Any]],
        task_id: str,
        *,
        session_id: Optional[str] = None,
        context_snapshot_id: Optional[str] = None,
    ) -> PolicyCheckResult:
        normalized = (tool_name or "").lower().replace(" ", "_").strip()

        # 1. Resolve the permission record exclusively from SQLite `permissions` table
        perm: Optional[ToolPermission] = get_permission(employee_id, normalized)

        if perm is None:
            result = PolicyCheckResult(
                allowed=False,
                reason=f"Tool '{normalized}' is not registered in this employee's toolbelt.",
                permission_level=None,
            )
            _log_policy_event(
                employee_id,
                task_id,
                "policy_check_block",
                result.reason,
                tool_name=normalized,
                session_id=session_id,
                context_snapshot_id=context_snapshot_id,
            )
            return result

        # 2. READ and ANALYZE never produce external side-effects
        if perm.permission in ("READ", "ANALYZE"):
            result = PolicyCheckResult(
                allowed=False,
                reason=f"Employee permission level '{perm.permission}' does not permit executing '{normalized}'.",
                permission_level=perm.permission,
            )
            _log_policy_event(
                employee_id,
                task_id,
                "policy_check_block",
                result.reason,
                tool_name=normalized,
                session_id=session_id,
                context_snapshot_id=context_snapshot_id,
            )
            return result

        # 3. DRAFT = may generate content in state but never dispatch external side-effect tools
        if perm.permission == "DRAFT":
            result = PolicyCheckResult(
                allowed=False,
                reason=(
                    f"DRAFT permission: '{normalized}' may be composed but not dispatched. "
                    f"Escalate to founder approval."
                ),
                permission_level=perm.permission,
            )
            _log_policy_event(
                employee_id,
                task_id,
                "policy_check_block",
                result.reason,
                tool_name=normalized,
                session_id=session_id,
                context_snapshot_id=context_snapshot_id,
            )
            return result

        # 4. Domain blacklist check for email_sender (enforced before both REQUEST and EXECUTE)
        if normalized == "email_sender" and tool_params:
            to_addr = str(tool_params.get("to") or "")
            blocked_domain = _extract_recipient_Blocked_domain(to_addr, _load_blacklisted_domains())
            if blocked_domain:
                result = PolicyCheckResult(
                    allowed=False,
                    reason=f"Hard block: recipient domain '{blocked_domain}' is on the organization blacklist.",
                    permission_level=perm.permission,
                )
                _log_policy_event(
                    employee_id,
                    task_id,
                    "policy_check_block",
                    result.reason,
                    tool_name=normalized,
                    session_id=session_id,
                    context_snapshot_id=context_snapshot_id,
                )
                return result

        # 5. REQUEST or requires_approval -> allowed to stage, routed to approval gate
        if perm.permission == "REQUEST" or perm.requires_approval:
            result = PolicyCheckResult(
                allowed=True,
                reason=f"Tool '{normalized}' requires founder approval before execution.",
                requires_approval=True,
                permission_level=perm.permission,
            )
            _log_policy_event(
                employee_id,
                task_id,
                "policy_check_pass",
                result.reason,
                tool_name=normalized,
                session_id=session_id,
                context_snapshot_id=context_snapshot_id,
            )
            return result

        # 6. EXECUTE with requires_approval=False -> immediate execution allowed
        result = PolicyCheckResult(
            allowed=True,
            reason=f"Permission check passed for '{normalized}' (level: {perm.permission}).",
            requires_approval=False,
            permission_level=perm.permission,
        )
        _log_policy_event(
            employee_id,
            task_id,
            "policy_check_pass",
            result.reason,
            tool_name=normalized,
            session_id=session_id,
            context_snapshot_id=context_snapshot_id,
        )
        return result

    @staticmethod
    def get_allowed_tools(employee_id: str, *, include_request: bool = True) -> List[str]:
        """Return tool IDs authorized in SQLite `permissions` for this employee."""
        perms = list_permissions(employee_id)
        allowed_levels = {"EXECUTE", "REQUEST"} if include_request else {"EXECUTE"}
        return [p.tool_id for p in perms if p.permission in allowed_levels]


def check_tool_permission(
    employee_id: str,
    tool_name: str,
    tool_params: Optional[Dict[str, Any]],
    task_id: str,
    *,
    session_id: Optional[str] = None,
    context_snapshot_id: Optional[str] = None,
) -> PolicyCheckResult:
    """Module-level entrypoint delegated to PolicyEngine."""
    return PolicyEngine.check_tool_permission(
        employee_id=employee_id,
        tool_name=tool_name,
        tool_params=tool_params,
        task_id=task_id,
        session_id=session_id,
        context_snapshot_id=context_snapshot_id,
    )


def _log_policy_event(
    employee_id: str,
    task_id: str,
    event_type: str,
    decision: str,
    *,
    tool_name: Optional[str] = None,
    session_id: Optional[str] = None,
    context_snapshot_id: Optional[str] = None,
) -> None:
    """Write an append-only policy check audit log entry."""
    entry = AuditLogEntry(
        id=f"audit_{uuid.uuid4().hex[:12]}",
        employee_id=employee_id,
        task_id=task_id,
        session_id=session_id,
        context_snapshot_id=context_snapshot_id,
        event_type=event_type,  # type: ignore[arg-type]
        tools_called=[tool_name] if tool_name else [],
        decision=decision,
        output_summary=decision,
        timestamp=_now(),
    )
    try:
        save_audit_log(entry)
    except Exception:
        pass  # Audit log failure must never crash the execution pipeline
