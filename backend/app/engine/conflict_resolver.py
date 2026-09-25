"""
Conflict Resolver — Phase 1

When a new MemoryRecord is proposed that might conflict with an existing active rule,
this module detects the conflict and surfaces it for founder resolution
rather than silently accumulating contradictory rules.

Conflict detection is conservative: it prefers to surface ambiguous cases
rather than silently supersede existing rules.
"""

from __future__ import annotations
from typing import Optional
from dataclasses import dataclass

from app.models.memory import MemoryRecord
from app.db.store import list_memories, save_memory


@dataclass
class ConflictReport:
    has_conflict: bool
    existing_rule: Optional[MemoryRecord]
    description: str


def _rules_overlap(existing: MemoryRecord, incoming: MemoryRecord) -> bool:
    """
    Check if two memory records are likely to conflict.
    Two rules conflict if they share the same employee, category, and overlapping scope.
    """
    if existing.employee_id != incoming.employee_id:
        return False
    if existing.category != incoming.category:
        return False

    # Scope overlap: 'global' conflicts with everything; specific scopes only conflict with each other
    scopes_overlap = (
        existing.scope == "global"
        or incoming.scope == "global"
        or existing.scope == incoming.scope
    )
    return scopes_overlap


def check_for_conflict(incoming: MemoryRecord) -> ConflictReport:
    """
    Check whether the incoming proposed memory conflicts with an existing active rule.
    Returns a ConflictReport the API layer can surface to the founder.
    """
    active_rules = list_memories(incoming.employee_id, status="active")

    for existing in active_rules:
        if _rules_overlap(existing, incoming):
            return ConflictReport(
                has_conflict=True,
                existing_rule=existing,
                description=(
                    f"Potential conflict detected:\n"
                    f"  Existing rule: \"{existing.distilled_rule}\"\n"
                    f"  Proposed rule: \"{incoming.distilled_rule}\"\n"
                    f"  Both apply to scope '{existing.scope}' in category '{existing.category}'.\n"
                    f"  Please confirm: supersede the existing rule, keep both, or reject the new one."
                ),
            )

    return ConflictReport(
        has_conflict=False,
        existing_rule=None,
        description="No conflict detected with existing active rules.",
    )


def apply_supersession(
    incoming: MemoryRecord,
    existing_id: str,
    founder_confirmed: bool,
) -> MemoryRecord:
    """
    When the founder confirms that the incoming rule supersedes an existing one:
    1. Set existing rule status to 'superseded'.
    2. Set incoming rule's supersedes field to the old rule's ID.
    3. Activate the incoming rule.

    Saves both records. Returns the now-active incoming record.
    """
    if not founder_confirmed:
        # Founder declined supersession — incoming stays 'proposed', existing stays 'active'
        return incoming

    # Deactivate the old rule
    old_rule = next(
        (r for r in list_memories(incoming.employee_id) if r.id == existing_id), None
    )
    if old_rule:
        old_rule.status = "superseded"
        save_memory(old_rule)

    # Link and activate the incoming rule
    incoming.supersedes = existing_id
    incoming.status = "active"
    from datetime import datetime
    incoming.activated_at = datetime.utcnow().isoformat()
    incoming.last_confirmed_at = incoming.activated_at
    save_memory(incoming)

    return incoming
