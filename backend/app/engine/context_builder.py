"""
Stage-Scoped Context Compiler (`ContextBuilder`) — Phase 4 (Maya v2 Frozen Contract)

Replaces the v1 "give Gemini everything in one giant prompt" anti-pattern with
stage-isolated, budget-bounded, immutable `ContextSnapshot` compilation.

Key Invariants:
  1. Stage Isolation: Each stage (`PLAN`, `COLLECT`, `VERIFY`, `QUALIFY`, `COMPOSE`,
     `REFLECT`) receives ONLY the fields, instructions, tools, and memories relevant
     to that stage. `VERIFY` and `QUALIFY` never receive `COMPOSE` outreach persona
     fluff or unrelated memories.
  2. Memory Filtering: Only `status == 'active'` memories matching BOTH
     `scope in {'global', task_scope}` AND `stage in memory.applies_to_stages`
     are eligible.
  3. Hard Context Budgets: Each stage enforces a strict `max_memories` count cap,
     `max_memory_chars` budget, and `max_stage_input_chars` budget.
  4. Full-Payload Canonical SHA-256 (`context_hash`): Hashes the canonical JSON of
     the entire compiled payload (`employee_id`, `config_version`, `stage`, `model`,
     `system_instruction`, `stage_input`, `memories`, `allowed_tools`) so any change
     in memories, tools, or inputs changes `context_hash`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.store import list_active_memories, save_audit_log, save_context_snapshot
from app.engine.policy_engine import PolicyEngine
from app.models.employee import AIEmployeeSpec
from app.models.memory import (
    AuditLogEntry,
    MemoryRecord,
    MemoryStage,
    normalize_memory_scope,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(data: Any) -> str:
    """Serialize any JSON-compatible structure deterministically."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StageBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_memories: int
    max_memory_chars: int
    max_stage_input_chars: int
    include_persona: bool
    include_sops: bool
    stage_tools: List[str]


STAGE_BUDGETS: Dict[MemoryStage, StageBudget] = {
    "PLAN": StageBudget(
        max_memories=5,
        max_memory_chars=1600,
        max_stage_input_chars=6000,
        include_persona=False,
        include_sops=True,
        stage_tools=["web_search"],
    ),
    "COLLECT": StageBudget(
        max_memories=2,
        max_memory_chars=600,
        max_stage_input_chars=8000,
        include_persona=False,
        include_sops=False,
        stage_tools=["web_search"],
    ),
    "VERIFY": StageBudget(
        max_memories=2,
        max_memory_chars=600,
        max_stage_input_chars=8000,
        include_persona=False,
        include_sops=False,
        stage_tools=[],
    ),
    "QUALIFY": StageBudget(
        max_memories=2,
        max_memory_chars=600,
        max_stage_input_chars=8000,
        include_persona=False,
        include_sops=False,
        stage_tools=[],
    ),
    "COMPOSE": StageBudget(
        max_memories=8,
        max_memory_chars=2800,
        max_stage_input_chars=12000,
        include_persona=True,
        include_sops=True,
        stage_tools=["email_sender", "sheet_logger", "slack_notifier"],
    ),
    "REFLECT": StageBudget(
        max_memories=3,
        max_memory_chars=1000,
        max_stage_input_chars=6000,
        include_persona=False,
        include_sops=False,
        stage_tools=[],
    ),
}


STAGE_DEFAULT_INSTRUCTIONS: Dict[MemoryStage, str] = {
    "PLAN": (
        "Compile the user task into structured requirements and concrete single-hop search queries. "
        "Distinguish high-observability fields from low-public-observability fields."
    ),
    "COLLECT": (
        "Extract candidate company names and canonical domains from discovery results with strict URL provenance."
    ),
    "VERIFY": (
        "Evaluate only mechanical verification signals captured from live HTTP headers and HTML footprints. "
        "Never infer unverified platform or paid subscription claims from text mentions."
    ),
    "QUALIFY": (
        "Evaluate candidate claims strictly against structured session requirements and supporting evidence IDs."
    ),
    "COMPOSE": (
        "Draft the deliverable and outreach strictly using whitelisted allowed_outreach_claims. "
        "Never fabricate contact emails, revenue figures, or unverified technical claims."
    ),
    "REFLECT": (
        "Analyze specific founder feedback and extract a reusable operational rule only when the feedback is clear and actionable."
    ),
}


class ContextSnapshot(BaseModel):
    """Immutable stage-specific context snapshot with canonical full-payload SHA-256 hash."""

    model_config = ConfigDict(frozen=True)

    id: str
    session_id: Optional[str] = None
    task_id: str
    employee_id: str
    stage: MemoryStage
    model: str
    memory_ids: List[str] = Field(default_factory=list)
    truncated_memory_ids: List[str] = Field(default_factory=list)
    allowed_tools: List[str] = Field(default_factory=list)
    payload: Dict[str, Any]
    payload_json: str
    context_hash: str
    created_at: str = Field(default_factory=_now)

    def to_llm_messages(self) -> List[Dict[str, str]]:
        """Render the compiled snapshot into strict system + user role messages for LLMGateway."""
        system_parts: List[str] = [
            f"STAGE: {self.stage}",
            f"INSTRUCTION: {self.payload.get('system_instruction', '')}",
        ]
        if self.payload.get("employee_profile"):
            profile = self.payload["employee_profile"]
            system_parts.append(
                f"EMPLOYEE: {profile.get('name')} ({profile.get('role')} - {profile.get('department')})"
            )
            if profile.get("persona"):
                system_parts.append(f"PERSONA: {profile['persona']}")
            if profile.get("sops"):
                sops_block = "\n".join(f"- {s}" for s in profile["sops"])
                system_parts.append(f"STANDARD OPERATING PROCEDURES:\n{sops_block}")

        if self.payload.get("memories"):
            mem_lines = [
                f"- [{m['category']}|{m['scope']}|P{m['priority']}] {m['title']}: {m['distilled_rule']}"
                for m in self.payload["memories"]
            ]
            system_parts.append("ACTIVE LEARNED RULES:\n" + "\n".join(mem_lines))

        if self.allowed_tools:
            system_parts.append(f"ALLOWED STAGE TOOLS: {', '.join(self.allowed_tools)}")

        user_content = canonical_json(self.payload.get("stage_input", {}))
        return [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": user_content},
        ]


def _truncate_stage_input(stage_input: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    """Bound stage_input deterministically if serialized representation exceeds max_chars."""
    serialized = canonical_json(stage_input)
    if len(serialized) <= max_chars:
        return stage_input

    bounded: Dict[str, Any] = {}
    remaining = max_chars
    for key in sorted(stage_input.keys()):
        val = stage_input[key]
        val_json = canonical_json(val)
        if len(val_json) <= remaining:
            bounded[key] = val
            remaining -= len(val_json)
        elif isinstance(val, str):
            bounded[key] = val[: max(0, remaining - 32)] + "...[TRUNCATED]"
            remaining = 0
        else:
            bounded[key] = val_json[: max(0, remaining - 32)] + "...[TRUNCATED]"
            remaining = 0
    bounded["_truncated"] = True
    return bounded


class ContextBuilder:
    """Compiles stage-isolated, budget-enforced ContextSnapshots."""

    @staticmethod
    def select_stage_memories(
        employee_id: str,
        stage: MemoryStage,
        *,
        task_scope: str = "global",
        memories_override: Optional[List[MemoryRecord]] = None,
        max_memories: Optional[int] = None,
        max_memory_chars: Optional[int] = None,
    ) -> tuple[List[MemoryRecord], List[str]]:
        """
        Filter and budget active memories for a given employee, stage, and task_scope.

        Returns `(selected_memories, truncated_memory_ids)`.
        """
        budget = STAGE_BUDGETS[stage]
        limit_count = budget.max_memories if max_memories is None else max_memories
        limit_chars = budget.max_memory_chars if max_memory_chars is None else max_memory_chars

        normalized_scope = normalize_memory_scope(task_scope)
        allowed_scopes = {"global", normalized_scope}

        raw_memories = (
            memories_override
            if memories_override is not None
            else list_active_memories(employee_id)
        )

        # Filter strictly by active status, scope match, and stage membership
        eligible: List[MemoryRecord] = []
        for mem in raw_memories:
            if mem.status != "active":
                continue
            if normalize_memory_scope(mem.scope) not in allowed_scopes:
                continue
            if stage not in (mem.applies_to_stages or ["PLAN", "COMPOSE"]):
                continue
            eligible.append(mem)

        # Deterministic sort: priority ASC (1=highest), created_at DESC, id ASC
        eligible.sort(key=lambda m: (m.priority, -(int(m.version or 1)), m.id))

        selected: List[MemoryRecord] = []
        truncated_ids: List[str] = []
        used_chars = 0

        for mem in eligible:
            entry_text = f"{mem.title}: {mem.distilled_rule}"
            entry_len = len(entry_text)
            if len(selected) >= limit_count or (used_chars + entry_len > limit_chars):
                truncated_ids.append(mem.id)
                continue
            selected.append(mem)
            used_chars += entry_len

        return selected, truncated_ids

    @classmethod
    def build(
        cls,
        *,
        employee: AIEmployeeSpec,
        stage: MemoryStage,
        task_id: str,
        stage_input: Dict[str, Any],
        session_id: Optional[str] = None,
        task_scope: str = "global",
        model: str = "gemini-2.5-flash",
        system_instruction: Optional[str] = None,
        memories_override: Optional[List[MemoryRecord]] = None,
        max_memories: Optional[int] = None,
        max_memory_chars: Optional[int] = None,
        persist: bool = True,
        log_audit: bool = True,
    ) -> ContextSnapshot:
        """
        Compile an immutable stage-specific ContextSnapshot and compute its canonical
        full-payload SHA-256 `context_hash`.
        """
        budget = STAGE_BUDGETS[stage]
        selected_memories, truncated_memory_ids = cls.select_stage_memories(
            employee.id,
            stage,
            task_scope=task_scope,
            memories_override=memories_override,
            max_memories=max_memories,
            max_memory_chars=max_memory_chars,
        )

        # Resolve stage-allowed tools strictly from SQLite `permissions` via PolicyEngine
        policy_allowed = set(PolicyEngine.get_allowed_tools(employee.id, include_request=True))
        allowed_tools = sorted(t for t in budget.stage_tools if t in policy_allowed)

        # Build stage-scoped employee profile (VERIFY/QUALIFY/COLLECT omit persona & SOP noise)
        employee_profile: Dict[str, Any] = {
            "id": employee.id,
            "name": employee.name,
            "role": employee.role,
            "department": employee.department,
        }
        if budget.include_persona:
            employee_profile["persona"] = employee.persona
            employee_profile["objective"] = employee.objective
        if budget.include_sops:
            employee_profile["sops"] = list(employee.sops or [])

        serialized_memories = [
            {
                "id": m.id,
                "category": m.category,
                "scope": m.scope,
                "priority": m.priority,
                "rule_key": m.rule_key,
                "title": m.title,
                "distilled_rule": m.distilled_rule,
                "version": m.version,
            }
            for m in selected_memories
        ]

        bounded_input = _truncate_stage_input(stage_input, budget.max_stage_input_chars)
        resolved_instruction = (
            system_instruction.strip()
            if system_instruction and system_instruction.strip()
            else STAGE_DEFAULT_INSTRUCTIONS[stage]
        )

        # Full canonical payload — hashing this entire structure guarantees that ANY change
        # to memories, tools, stage_input, model, or instruction alters context_hash.
        canonical_payload: Dict[str, Any] = {
            "stage": stage,
            "model": model,
            "employee_id": employee.id,
            "task_scope": normalize_memory_scope(task_scope),
            "system_instruction": resolved_instruction,
            "employee_profile": employee_profile,
            "allowed_tools": allowed_tools,
            "memories": serialized_memories,
            "truncated_memory_ids": truncated_memory_ids,
            "stage_input": bounded_input,
        }

        payload_json = canonical_json(canonical_payload)
        context_hash = sha256_hex(payload_json)
        snapshot_id = f"ctx_{uuid.uuid4().hex[:12]}"
        created_at = _now()

        snapshot = ContextSnapshot(
            id=snapshot_id,
            session_id=session_id,
            task_id=task_id,
            employee_id=employee.id,
            stage=stage,
            model=model,
            memory_ids=[m.id for m in selected_memories],
            truncated_memory_ids=truncated_memory_ids,
            allowed_tools=allowed_tools,
            payload=canonical_payload,
            payload_json=payload_json,
            context_hash=context_hash,
            created_at=created_at,
        )

        if persist and session_id:
            try:
                save_context_snapshot(snapshot)
            except Exception:
                pass

        if log_audit:
            try:
                save_audit_log(
                    AuditLogEntry(
                        id=f"audit_{uuid.uuid4().hex[:12]}",
                        employee_id=employee.id,
                        task_id=task_id,
                        session_id=session_id,
                        context_snapshot_id=snapshot.id,
                        event_type="context_built",
                        prompt_version=context_hash,
                        memories_used=snapshot.memory_ids,
                        tools_called=allowed_tools,
                        decision=f"Compiled {stage} ContextSnapshot ({len(snapshot.memory_ids)} memories, hash={context_hash[:12]}).",
                        output_summary=f"stage={stage} memories={len(snapshot.memory_ids)} truncated={len(truncated_memory_ids)}",
                        timestamp=created_at,
                    )
                )
            except Exception:
                pass

        return snapshot
