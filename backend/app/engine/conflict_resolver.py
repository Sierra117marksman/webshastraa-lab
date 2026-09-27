"""
Memory Conflict & Supersession Resolver — Phase 4 (Maya v2 Frozen Contract)

Invariants:
  1. Never silently overwrite an active memory rule.
  2. Detect conflicts via both canonical `rule_key` equality and `(category, scope)`
     semantic topic overlap.
  3. Execute conflict resolution (`SUPERSEDE`, `KEEP_BOTH`, `REJECT`) inside a
     single atomic SQLite transaction (`with transaction(store.DB_PATH):`),
     updating memory row(s) and appending an immutable `AuditLogEntry` together.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional, Set

import app.db.store as _store_mod
from app.db.connection import transaction
from app.db.store import list_active_memories
from app.models.memory import AuditLogEntry, MemoryRecord, normalize_memory_scope

ResolutionAction = Literal["SUPERSEDE", "KEEP_BOTH", "REJECT"]

_STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "that", "this", "from", "into", "only",
    "must", "never", "always", "keep", "use", "when", "all", "are", "not",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_topic_tokens(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9]{3,}", (text or "").casefold())
    return {w for w in words if w not in _STOPWORDS and not w.isdigit()}


class ConflictCheckResult:
    def __init__(
        self,
        has_conflict: bool,
        existing_rule: Optional[MemoryRecord] = None,
        description: str = "",
        conflict_type: Optional[str] = None,
    ):
        self.has_conflict = has_conflict
        self.existing_rule = existing_rule
        self.description = description
        self.conflict_type = conflict_type


def check_for_conflict(incoming: MemoryRecord) -> ConflictCheckResult:
    """
    Check whether `incoming` conflicts with any currently ACTIVE memory for the same employee.

    Detection hierarchy:
      1. Exact canonical `rule_key` match on an active memory.
      2. Same `category` and overlapping `scope` (`existing.scope == incoming.scope` or
         either is `'global'` with shared topic tokens in title/distilled_rule).
    """
    active_memories: List[MemoryRecord] = list_active_memories(incoming.employee_id)
    incoming_scope = normalize_memory_scope(incoming.scope)
    incoming_tokens = _extract_topic_tokens(f"{incoming.title} {incoming.distilled_rule}")

    # Pass 1: Exact rule_key match
    for existing in active_memories:
        if existing.id == incoming.id:
            continue
        if existing.rule_key and incoming.rule_key and existing.rule_key == incoming.rule_key:
            return ConflictCheckResult(
                has_conflict=True,
                existing_rule=existing,
                conflict_type="rule_key_match",
                description=(
                    f"Exact rule_key conflict ('{incoming.rule_key}') with active rule "
                    f"[{existing.id}] '{existing.title}' (v{existing.version}):\n"
                    f"  Existing: \"{existing.distilled_rule}\"\n"
                    f"  Incoming: \"{incoming.distilled_rule}\""
                ),
            )

    # Pass 2: Same category & scope overlap
    for existing in active_memories:
        if existing.id == incoming.id:
            continue
        if existing.category != incoming.category:
            continue

        existing_scope = normalize_memory_scope(existing.scope)
        same_specific_scope = existing_scope == incoming_scope and incoming_scope != "global"
        same_global_scope = existing_scope == incoming_scope == "global"
        cross_global_scope = existing_scope == "global" or incoming_scope == "global"

        existing_tokens = _extract_topic_tokens(f"{existing.title} {existing.distilled_rule}")
        shared_tokens = incoming_tokens & existing_tokens

        if same_specific_scope or (same_global_scope and shared_tokens) or (cross_global_scope and len(shared_tokens) >= 2):
            return ConflictCheckResult(
                has_conflict=True,
                existing_rule=existing,
                conflict_type="scope_category_overlap",
                description=(
                    f"Potential conflict with active rule [{existing.id}] '{existing.title}' "
                    f"(v{existing.version}, scope='{existing_scope}'):\n"
                    f"  Existing: \"{existing.distilled_rule}\"\n"
                    f"  Incoming: \"{incoming.distilled_rule}\"\n"
                    f"Confirm whether the new rule should SUPERSEDE [{existing.id}], KEEP_BOTH, or REJECT."
                ),
            )

    return ConflictCheckResult(has_conflict=False)


def _upsert_memory_row_in_tx(conn: sqlite3.Connection, memory: MemoryRecord) -> None:
    data = memory.model_dump()
    rule_key = (
        memory.rule_key
        or data.get("rule_key")
        or f"memory:{memory.category}:{str(memory.scope)}:{memory.title.strip().casefold()}"
    )
    data["rule_key"] = rule_key
    applies_to_stages = data.get("applies_to_stages") or ["PLAN", "COMPOSE"]
    data["applies_to_stages"] = applies_to_stages
    values = (
        memory.id,
        memory.employee_id,
        memory.category,
        str(memory.scope),
        json.dumps(applies_to_stages, ensure_ascii=False),
        rule_key,
        memory.title,
        memory.distilled_rule,
        memory.status,
        memory.priority,
        memory.confidence_score,
        memory.version,
        memory.supersedes,
        json.dumps(data, ensure_ascii=False),
        memory.created_at,
        memory.activated_at,
    )
    exists = conn.execute("SELECT 1 FROM memories WHERE id = ?", (memory.id,)).fetchone()
    if exists:
        conn.execute(
            """
            UPDATE memories SET employee_id=?, category=?, scope=?, applies_to_stages_json=?, rule_key=?,
                title=?, distilled_rule=?, status=?, priority=?, confidence_score=?, version=?, supersedes=?,
                data=?, created_at=?, activated_at=? WHERE id=?
            """,
            (*values[1:], values[0]),
        )
    else:
        conn.execute(
            """
            INSERT INTO memories (
                id, employee_id, category, scope, applies_to_stages_json, rule_key, title, distilled_rule,
                status, priority, confidence_score, version, supersedes, data, created_at, activated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )


def _insert_audit_row_in_tx(conn: sqlite3.Connection, entry: AuditLogEntry) -> None:
    data = entry.model_dump()
    conn.execute(
        """
        INSERT INTO audit_log (
            id, employee_id, task_id, session_id, context_snapshot_id,
            event_type, timestamp, data
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.id,
            entry.employee_id,
            entry.task_id,
            data.get("session_id"),
            data.get("context_snapshot_id"),
            entry.event_type,
            entry.timestamp,
            json.dumps(data, ensure_ascii=False),
        ),
    )


def resolve_memory_conflict(
    incoming: MemoryRecord,
    existing_id: Optional[str],
    action: ResolutionAction,
    *,
    founder_confirmed: bool = True,
    task_id: str = "memory_governance",
) -> MemoryRecord:
    """
    Atomically resolve a memory conflict inside a single SQLite transaction.

    Supported actions:
      - 'SUPERSEDE': Marks `existing_id` as 'superseded', links `incoming.supersedes = existing_id`,
        increments `incoming.version = existing.version + 1`, and sets `incoming.status` to
        `'active'` (if `founder_confirmed=True`) or `'proposed'`.
      - 'KEEP_BOTH': Leaves `existing_id` untouched as `'active'` and saves `incoming` as
        `'active'` (if `founder_confirmed=True`) or `'proposed'`, disambiguating `incoming.rule_key`
        if identical.
      - 'REJECT': Leaves `existing_id` untouched and records `incoming` with `status='rejected'`.
    """
    now = _now()

    with transaction(_store_mod.DB_PATH) as conn:
        existing: Optional[MemoryRecord] = None
        if existing_id:
            row = conn.execute(
                "SELECT data, rule_key, applies_to_stages_json FROM memories WHERE id = ?",
                (existing_id,),
            ).fetchone()
            if row:
                payload = json.loads(row["data"])
                if row["rule_key"] and not payload.get("rule_key"):
                    payload["rule_key"] = row["rule_key"]
                existing = MemoryRecord(**payload)

        if action == "SUPERSEDE":
            if existing is not None:
                existing.status = "superseded"
                existing.last_confirmed_at = now
                _upsert_memory_row_in_tx(conn, existing)
                incoming.version = existing.version + 1
                incoming.supersedes = existing.id
            else:
                incoming.supersedes = existing_id

            incoming.last_confirmed_at = now
            if founder_confirmed:
                incoming.status = "active"
                incoming.activated_at = now
            else:
                incoming.status = "proposed"

            _upsert_memory_row_in_tx(conn, incoming)
            _insert_audit_row_in_tx(
                conn,
                AuditLogEntry(
                    id=f"audit_{uuid.uuid4().hex[:12]}",
                    employee_id=incoming.employee_id,
                    task_id=task_id,
                    event_type="memory_superseded",
                    memories_used=[m for m in [existing_id, incoming.id] if m],
                    decision=f"SUPERSEDE: '{incoming.title}' (v{incoming.version}) superseded '{existing_id}'.",
                    output_summary=incoming.distilled_rule,
                    timestamp=now,
                ),
            )
            return incoming

        if action == "KEEP_BOTH":
            if existing is not None and incoming.rule_key == existing.rule_key:
                incoming.rule_key = f"{incoming.rule_key}:{incoming.id}"
            incoming.last_confirmed_at = now
            if founder_confirmed:
                incoming.status = "active"
                incoming.activated_at = now
            else:
                incoming.status = "proposed"

            _upsert_memory_row_in_tx(conn, incoming)
            _insert_audit_row_in_tx(
                conn,
                AuditLogEntry(
                    id=f"audit_{uuid.uuid4().hex[:12]}",
                    employee_id=incoming.employee_id,
                    task_id=task_id,
                    event_type="memory_conflict_resolved",
                    memories_used=[m for m in [existing_id, incoming.id] if m],
                    decision=f"KEEP_BOTH: Kept existing '{existing_id}' and activated '{incoming.id}'.",
                    output_summary=incoming.distilled_rule,
                    timestamp=now,
                ),
            )
            return incoming

        if action == "REJECT":
            incoming.status = "rejected"
            incoming.last_confirmed_at = now
            _upsert_memory_row_in_tx(conn, incoming)
            _insert_audit_row_in_tx(
                conn,
                AuditLogEntry(
                    id=f"audit_{uuid.uuid4().hex[:12]}",
                    employee_id=incoming.employee_id,
                    task_id=task_id,
                    event_type="memory_rejected",
                    memories_used=[m for m in [existing_id, incoming.id] if m],
                    decision=f"REJECT: Rejected incoming memory '{incoming.id}' in favor of '{existing_id}'.",
                    output_summary=incoming.distilled_rule,
                    timestamp=now,
                ),
            )
            return incoming

        raise ValueError(f"Unsupported conflict resolution action: {action!r}")


def apply_supersession(
    incoming: MemoryRecord,
    existing_id: str,
    founder_confirmed: bool = False,
) -> MemoryRecord:
    """Backward-compatible wrapper that executes a transactional SUPERSEDE resolution."""
    return resolve_memory_conflict(
        incoming=incoming,
        existing_id=existing_id,
        action="SUPERSEDE",
        founder_confirmed=founder_confirmed,
    )
