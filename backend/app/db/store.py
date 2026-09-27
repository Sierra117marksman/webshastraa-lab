"""SQLite repositories for the Phase 1 Maya v2 persistence layer.

The repository keeps the existing model-facing functions for compatibility while
moving all writes to explicit INSERT/UPDATE statements and transactional helpers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.employee import AIEmployeeSpec, TaskRecord
from app.models.memory import MemoryRecord, AuditLogEntry, ToolPermission, SEEDED_PERMISSIONS

from .connection import DB_PATH, get_connection, transaction
from .migrations import run_migrations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(model_or_dict: Any) -> Dict[str, Any]:
    if hasattr(model_or_dict, "model_dump"):
        return model_or_dict.model_dump()
    if isinstance(model_or_dict, dict):
        return dict(model_or_dict)
    raise TypeError(f"Unsupported repository object: {type(model_or_dict)!r}")


def init_db() -> None:
    run_migrations(DB_PATH)
    seed_templates_if_empty()
    seed_permissions_if_empty()


# ---------------------------------------------------------------------------
# Employee / Task repositories
# ---------------------------------------------------------------------------


def save_employee(employee: AIEmployeeSpec) -> None:
    data = _dump(employee)
    sops_json = json.dumps(data.get("sops", []), ensure_ascii=False)
    with transaction(DB_PATH) as conn:
        existing = conn.execute("SELECT 1 FROM employees WHERE id = ?", (employee.id,)).fetchone()
        values = (
            employee.id,
            employee.name,
            data.get("role", "Autonomous Agent"),
            employee.department,
            data.get("objective", ""),
            data.get("persona", ""),
            sops_json,
            data.get("schedule_type", "on_demand"),
            data.get("schedule_interval_mins"),
            data.get("status", "active"),
            int(data.get("config_version", 1)),
            json.dumps(data, ensure_ascii=False),
            data.get("created_at") or _now(),
        )
        if existing:
            conn.execute(
                """
                UPDATE employees
                SET name=?, role=?, department=?, objective=?, persona=?, sops_json=?,
                    schedule_type=?, schedule_interval_mins=?, status=?, config_version=?, data=?
                WHERE id=?
                """,
                (*values[1:11], values[11], values[0]),
            )
        else:
            conn.execute(
                """
                INSERT INTO employees (
                    id, name, role, department, objective, persona, sops_json,
                    schedule_type, schedule_interval_mins, status, config_version, data, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )


def get_employee(employee_id: str) -> Optional[AIEmployeeSpec]:
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute("SELECT data FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return AIEmployeeSpec(**json.loads(row["data"])) if row else None
    finally:
        conn.close()


def list_employees() -> List[AIEmployeeSpec]:
    conn = get_connection(DB_PATH)
    try:
        rows = conn.execute("SELECT data FROM employees ORDER BY created_at DESC").fetchall()
        return [AIEmployeeSpec(**json.loads(r["data"])) for r in rows]
    finally:
        conn.close()


def delete_employee(employee_id: str) -> None:
    # employees -> tasks/memories/permissions cascade. Audit is deliberately retained.
    with transaction(DB_PATH) as conn:
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))


def save_task(task: TaskRecord) -> None:
    data = _dump(task)
    with transaction(DB_PATH) as conn:
        exists = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task.id,)).fetchone()
        values = (
            task.id,
            task.employee_id,
            data.get("session_id"),
            task.task_prompt,
            data.get("status", "pending"),
            data.get("resume_state"),
            json.dumps(data.get("pending_action"), ensure_ascii=False) if data.get("pending_action") is not None else None,
            data.get("final_output"),
            int(data.get("tokens_used", 0)),
            float(data.get("cost_usd", 0.0)),
            json.dumps(data, ensure_ascii=False),
            data.get("created_at") or _now(),
            data.get("completed_at"),
        )
        if exists:
            conn.execute(
                """
                UPDATE tasks SET employee_id=?, session_id=?, task_prompt=?, status=?, resume_state=?,
                    pending_action_json=?, final_output=?, tokens_used=?, cost_usd=?, data=?, completed_at=?
                WHERE id=?
                """,
                (values[1], values[2], values[3], values[4], values[5], values[6], values[7], values[8], values[9], values[10], values[12], values[0]),
            )
        else:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, employee_id, session_id, task_prompt, status, resume_state,
                    pending_action_json, final_output, tokens_used, cost_usd, data, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )


def get_task(task_id: str) -> Optional[TaskRecord]:
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute("SELECT data FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return TaskRecord(**json.loads(row["data"])) if row else None
    finally:
        conn.close()


def list_tasks(limit: int = 50) -> List[TaskRecord]:
    conn = get_connection(DB_PATH)
    try:
        rows = conn.execute("SELECT data FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [TaskRecord(**json.loads(r["data"])) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def seed_templates_if_empty() -> None:
    conn = get_connection(DB_PATH)
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0])
    finally:
        conn.close()
    if count:
        return

    templates = [
        AIEmployeeSpec(
            id="emp_sdr_01", name="Maya Vance", role="B2B Sales Development Rep (SDR)", department="CRM",
            avatar_emoji="🎯", theme_color="emerald",
            objective="Identify ideal target accounts, research decision makers, and draft personalized high-converting cold outreach.",
            persona="Professional, concise, consultative, and hyper-personalized.",
            sops=[
                "1. Search for target companies and their recent news or pain points.",
                "2. Formulate a 3-sentence value proposition matching their industry.",
                "3. Draft an email with a clear soft CTA (e.g. 15-min chat next Tuesday).",
                "4. ALWAYS request approval before transmitting external emails.",
            ],
            tools=["web_search", "email_sender", "sheet_logger"], schedule_type="daily",
            requires_approval_for=["email_sender"],
        ),
        AIEmployeeSpec(
            id="emp_hr_01", name="Arjun Patel", role="Talent & Resume Screening Specialist", department="HRM",
            avatar_emoji="📋", theme_color="indigo",
            objective="Parse applicant profiles, cross-reference required skills, score candidates, and draft interview invitations.",
            persona="Fair, empathetic, rigorous with technical and cultural criteria.",
            sops=[
                "1. Review candidate profile against job specification requirements.",
                "2. Score candidate on 1-10 scale across technical competence and cultural fit.",
                "3. Draft tailored screening email to qualified applicants.",
            ],
            tools=["sheet_logger", "email_sender"], schedule_type="on_demand",
            requires_approval_for=["email_sender"],
        ),
        AIEmployeeSpec(
            id="emp_mkt_01", name="Chloe Chen", role="Growth Marketing & Competitor Intel Analyst", department="Marketing",
            avatar_emoji="🚀", theme_color="purple",
            objective="Monitor industry trends, dissect competitor feature launches, and generate viral LinkedIn/Twitter thought leadership posts.",
            persona="Sharp, trend-aware, high-energy storytelling.",
            sops=[
                "1. Search for breaking AI and market announcements in the specified niche.",
                "2. Extract actionable takeaways for early-stage founders.",
                "3. Draft 2 LinkedIn hook variations and a comprehensive thought leadership breakdown.",
            ],
            tools=["web_search", "sheet_logger", "slack_notifier"], schedule_type="interval", schedule_interval_mins=360,
            requires_approval_for=[],
        ),
        AIEmployeeSpec(
            id="emp_ops_01", name="David Kim", role="Operations & Cashflow Reconciliation Guard", department="Operations",
            avatar_emoji="⚡", theme_color="amber",
            objective="Reconcile vendor invoices, deterministically audit billing math and contract caps, enforce strict evidence boundaries, and draft reconciliation holds for human finance sign-off.",
            persona="Organized, mathematically meticulous, respectful yet firm on contract adherence and evidence boundaries.",
            sops=[
                "1. Deterministic Mathematical Verification: Independently recalculate all hourly rates, fee percentages, and base salary calculations. Compare calculated amount against both submitted amount and contract cap.",
                "2. Strict Evidence Boundary: Audit only against facts, amounts, and descriptions explicitly provided in the submission; never assume or assert unverified usage records, logs, or external practices.",
                "3. Recommendation Authority Demarcation: You are an auditor and reconciliation analyst, NOT the disbursement authority. Issue strict recommendations (RECOMMEND PASS for human finance sign-off / RECOMMEND HOLD for vendor revision); never claim direct payment authorization or immediate payout approval.",
                "4. Zero Contact Fabrication: Never invent email addresses not supplied in the input context. Format missing fields as [NOT PROVIDED IN SUBMISSION - REQUIRES MANUAL ENTRY].",
                "5. Communication Drafts: Draft professional, contractually grounded inquiry notes with clear mathematical breakdowns for any flagged account.",
            ],
            tools=["sheet_logger", "email_sender", "slack_notifier"], schedule_type="daily",
            requires_approval_for=["email_sender"],
        ),
    ]
    for employee in templates:
        save_employee(employee)


def seed_permissions_if_empty() -> None:
    conn = get_connection(DB_PATH)
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM permissions").fetchone()[0])
    finally:
        conn.close()
    if count:
        return
    with transaction(DB_PATH) as conn:
        for employee_id, perms in SEEDED_PERMISSIONS.items():
            for permission in perms:
                conn.execute(
                    """
                    INSERT INTO permissions (employee_id, tool_id, permission, requires_approval, notes, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        employee_id,
                        permission.tool_id,
                        permission.permission,
                        1 if permission.requires_approval else 0,
                        permission.notes,
                        _now(),
                    ),
                )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def save_permission(employee_id: str, perm: ToolPermission) -> None:
    with transaction(DB_PATH) as conn:
        exists = conn.execute(
            "SELECT 1 FROM permissions WHERE employee_id = ? AND tool_id = ?",
            (employee_id, perm.tool_id),
        ).fetchone()
        args = (perm.permission, 1 if perm.requires_approval else 0, perm.notes, _now(), employee_id, perm.tool_id)
        if exists:
            conn.execute(
                "UPDATE permissions SET permission=?, requires_approval=?, notes=?, updated_at=? WHERE employee_id=? AND tool_id=?",
                args,
            )
        else:
            conn.execute(
                """
                INSERT INTO permissions (employee_id, tool_id, permission, requires_approval, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (employee_id, perm.tool_id, perm.permission, 1 if perm.requires_approval else 0, perm.notes, _now()),
            )


def list_permissions(employee_id: str) -> List[ToolPermission]:
    conn = get_connection(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT tool_id, permission, requires_approval, notes FROM permissions WHERE employee_id = ? ORDER BY tool_id",
            (employee_id,),
        ).fetchall()
        return [ToolPermission(tool_id=r["tool_id"], permission=r["permission"], requires_approval=bool(r["requires_approval"]), notes=r["notes"]) for r in rows]
    finally:
        conn.close()


def get_permission(employee_id: str, tool_id: str) -> Optional[ToolPermission]:
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute(
            "SELECT tool_id, permission, requires_approval, notes FROM permissions WHERE employee_id = ? AND tool_id = ?",
            (employee_id, tool_id),
        ).fetchone()
        if not row:
            return None
        return ToolPermission(tool_id=row["tool_id"], permission=row["permission"], requires_approval=bool(row["requires_approval"]), notes=row["notes"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def save_memory(memory: MemoryRecord) -> None:
    data = _dump(memory)
    rule_key = (
        memory.rule_key
        or data.get("rule_key")
        or f"memory:{memory.category}:{str(memory.scope)}:{memory.title.strip().casefold()}"
    )
    data["rule_key"] = rule_key
    applies_to_stages = data.get("applies_to_stages") or ["PLAN", "COMPOSE"]
    data["applies_to_stages"] = applies_to_stages
    values = (
        memory.id, memory.employee_id, memory.category, str(memory.scope),
        json.dumps(applies_to_stages, ensure_ascii=False),
        rule_key,
        memory.title, memory.distilled_rule, memory.status, memory.priority,
        memory.confidence_score, memory.version, memory.supersedes,
        json.dumps(data, ensure_ascii=False), memory.created_at, memory.activated_at,
    )
    with transaction(DB_PATH) as conn:
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


def _hydrate_memory_row(row: Any) -> MemoryRecord:
    payload = json.loads(row["data"])
    if "rule_key" in row.keys() and row["rule_key"] and not payload.get("rule_key"):
        payload["rule_key"] = row["rule_key"]
    if "applies_to_stages_json" in row.keys() and row["applies_to_stages_json"] and not payload.get("applies_to_stages"):
        try:
            payload["applies_to_stages"] = json.loads(row["applies_to_stages_json"])
        except Exception:
            pass
    return MemoryRecord(**payload)


def get_memory(memory_id: str) -> Optional[MemoryRecord]:
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute(
            "SELECT data, rule_key, applies_to_stages_json FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        return _hydrate_memory_row(row) if row else None
    finally:
        conn.close()


def list_memories(employee_id: str, status: Optional[str] = None) -> List[MemoryRecord]:
    conn = get_connection(DB_PATH)
    try:
        if status:
            rows = conn.execute(
                "SELECT data, rule_key, applies_to_stages_json FROM memories WHERE employee_id = ? AND status = ? ORDER BY priority ASC, created_at DESC",
                (employee_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT data, rule_key, applies_to_stages_json FROM memories WHERE employee_id = ? ORDER BY created_at DESC",
                (employee_id,),
            ).fetchall()
        return [_hydrate_memory_row(r) for r in rows]
    finally:
        conn.close()


def list_active_memories(employee_id: str) -> List[MemoryRecord]:
    return list_memories(employee_id, status="active")


def delete_memory(memory_id: str) -> None:
    # Preserve the old API but do not physically delete history. A deleted memory is rejected.
    with transaction(DB_PATH) as conn:
        conn.execute(
            "UPDATE memories SET status='rejected', data=json_set(data, '$.status', 'rejected') WHERE id = ?",
            (memory_id,),
        )


# ---------------------------------------------------------------------------
# Append-only audit log
# ---------------------------------------------------------------------------


def save_audit_log(entry: AuditLogEntry) -> None:
    data = _dump(entry)
    with transaction(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                id, employee_id, task_id, session_id, context_snapshot_id,
                event_type, timestamp, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id, entry.employee_id, entry.task_id,
                data.get("session_id"), data.get("context_snapshot_id"),
                entry.event_type, entry.timestamp, json.dumps(data, ensure_ascii=False),
            ),
        )


def list_audit_log(
    employee_id: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 100,
) -> List[AuditLogEntry]:
    conn = get_connection(DB_PATH)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT data FROM audit_log{where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [AuditLogEntry(**json.loads(r["data"])) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Context Snapshots & Session Metrics
# ---------------------------------------------------------------------------


def save_context_snapshot(snapshot: Any) -> bool:
    """Persist a ContextSnapshot row into context_snapshots if session_id exists in research_sessions."""
    data = _dump(snapshot)
    session_id = data.get("session_id")
    if not session_id:
        return False
    with transaction(DB_PATH) as conn:
        session_exists = conn.execute(
            "SELECT 1 FROM research_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not session_exists:
            return False
        conn.execute(
            """
            INSERT OR REPLACE INTO context_snapshots (
                id, session_id, task_id, employee_id, stage, model,
                memory_ids_json, allowed_tools_json, payload_json, context_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                session_id,
                data["task_id"],
                data["employee_id"],
                data["stage"],
                data["model"],
                json.dumps(data.get("memory_ids", []), ensure_ascii=False),
                json.dumps(data.get("allowed_tools", []), ensure_ascii=False),
                data.get("payload_json") or json.dumps(data.get("payload", {}), sort_keys=True, ensure_ascii=False),
                data["context_hash"],
                data.get("created_at") or _now(),
            ),
        )
        return True


def get_context_snapshot(snapshot_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT id, session_id, task_id, employee_id, stage, model,
                   memory_ids_json, allowed_tools_json, payload_json, context_hash, created_at
            FROM context_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "task_id": row["task_id"],
            "employee_id": row["employee_id"],
            "stage": row["stage"],
            "model": row["model"],
            "memory_ids": json.loads(row["memory_ids_json"]),
            "allowed_tools": json.loads(row["allowed_tools_json"]),
            "payload_json": row["payload_json"],
            "payload": json.loads(row["payload_json"]),
            "context_hash": row["context_hash"],
            "created_at": row["created_at"],
        }
    finally:
        conn.close()


def get_session_metrics(session_id: str) -> Dict[str, int]:
    conn = get_connection(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT qualification_status, COUNT(*) AS count
            FROM candidates
            WHERE session_id = ?
            GROUP BY qualification_status
            """,
            (session_id,),
        ).fetchall()
        metrics = {"candidates": 0, "pending": 0, "verified": 0, "prospect": 0, "rejected": 0}
        for row in rows:
            status = row["qualification_status"]
            count = int(row["count"])
            metrics["candidates"] += count
            if status == "PENDING":
                metrics["pending"] = count
            elif status == "VERIFIED":
                metrics["verified"] = count
            elif status == "PROSPECT":
                metrics["prospect"] = count
            elif status == "REJECTED":
                metrics["rejected"] = count
        return metrics
    finally:
        conn.close()


def get_task_research_ledger(task_id: str) -> Optional[Dict[str, Any]]:
    """Build the full Phase 6 Founder Command Center research ledger for a task."""
    task = get_task(task_id)
    if not task:
        return None

    conn = get_connection(DB_PATH)
    try:
        sess_row = conn.execute(
            """
            SELECT id, task_id, employee_id, raw_prompt, status,
                   target_verified_leads, allow_prospects, current_hop, max_hops,
                   verification_requests_made, search_queries_json, termination_reason,
                   created_at, updated_at
            FROM research_sessions
            WHERE task_id = ? OR id = ?
            LIMIT 1
            """,
            (task.id, task.session_id or ""),
        ).fetchone()
        if not sess_row:
            return None

        session_id = sess_row["id"]
        raw_prompt = sess_row["raw_prompt"] or task.task_prompt
        prompt_lower = raw_prompt.lower()
        session_status = sess_row["status"]
        target_count = int(sess_row["target_verified_leads"] or 10)
        current_hop = int(sess_row["current_hop"] or 0)
        max_hops = int(sess_row["max_hops"] or 4)

        req_rows = conn.execute(
            """
            SELECT id, field, operator, expected_json, priority, on_unknown,
                   observability_class, evidence_required, allowed_source_types_json
            FROM session_requirements
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
        requirements = []
        for r in req_rows:
            try:
                exp = json.loads(r["expected_json"])
            except Exception:
                exp = r["expected_json"]
            requirements.append({
                "id": r["id"],
                "field": r["field"],
                "operator": r["operator"],
                "expected": exp,
                "priority": r["priority"],
                "on_unknown": r["on_unknown"],
                "observability_class": r["observability_class"],
            })

        cand_rows = conn.execute(
            """
            SELECT id, company_name, canonical_domain, initial_url, final_url,
                   discovered_from_url, discovery_hop, http_reachable, http_status,
                   page_available, storefront_state, audited_by_verifier,
                   qualification_status, latest_decision_id, created_at, updated_at
            FROM candidates
            WHERE session_id = ?
            ORDER BY
                CASE qualification_status
                    WHEN 'VERIFIED' THEN 0
                    WHEN 'PROSPECT' THEN 1
                    WHEN 'PENDING' THEN 2
                    ELSE 3
                END ASC,
                rowid ASC
            """,
            (session_id,),
        ).fetchall()

        metrics = get_session_metrics(session_id)
        audited_count = sum(1 for c in cand_rows if bool(c["audited_by_verifier"]))
        total_candidates = len(cand_rows)

        candidates_payload: List[Dict[str, Any]] = []
        for c in cand_rows:
            cid = c["id"]
            ev_rows = conn.execute(
                """
                SELECT id, verifier_version, source_url, source_type,
                       supports_field, signal_type, extracted_value, raw_excerpt,
                       content_hash, confidence, financial_period, retrieved_at
                FROM evidence
                WHERE session_id = ? AND candidate_id = ?
                ORDER BY retrieved_at ASC, id ASC
                """,
                (session_id, cid),
            ).fetchall()
            evidence_list = [dict(e) for e in ev_rows]

            cl_rows = conn.execute(
                """
                SELECT id, field, value, status, notes, version, updated_at
                FROM claims
                WHERE session_id = ? AND candidate_id = ?
                ORDER BY field ASC
                """,
                (session_id, cid),
            ).fetchall()
            claims_list = [dict(cl) for cl in cl_rows]
            claims_by_field = {cl["field"]: dict(cl) for cl in cl_rows}

            dec_row = conn.execute(
                """
                SELECT id, hop, result, decision_hash, claims_snapshot_json,
                       requirement_results_json, supporting_claim_ids_json,
                       supporting_evidence_ids_json, notes_json, decided_at
                FROM qualification_decisions
                WHERE session_id = ? AND candidate_id = ?
                ORDER BY hop DESC, decided_at DESC
                LIMIT 1
                """,
                (session_id, cid),
            ).fetchone()

            decision_dict: Optional[Dict[str, Any]] = None
            req_eval_by_field: Dict[str, Dict[str, Any]] = {}
            rejection_reason: Optional[str] = None
            if dec_row:
                try:
                    notes_list = json.loads(dec_row["notes_json"] or "[]")
                    if isinstance(notes_list, list) and notes_list:
                        rejection_reason = "; ".join(str(n) for n in notes_list if n)
                    elif isinstance(notes_list, str) and notes_list:
                        rejection_reason = notes_list
                except Exception:
                    rejection_reason = dec_row["notes_json"]
                try:
                    req_res_raw = json.loads(dec_row["requirement_results_json"] or "{}")
                except Exception:
                    req_res_raw = {}
                if isinstance(req_res_raw, list):
                    for ev_obj in req_res_raw:
                        if isinstance(ev_obj, dict) and ev_obj.get("field"):
                            req_eval_by_field[ev_obj["field"]] = ev_obj
                elif isinstance(req_res_raw, dict):
                    for _, ev_obj in req_res_raw.items():
                        if isinstance(ev_obj, dict) and ev_obj.get("field"):
                            req_eval_by_field[ev_obj["field"]] = ev_obj
                decision_dict = {
                    "id": dec_row["id"],
                    "hop": dec_row["hop"],
                    "result": dec_row["result"],
                    "decision_hash": dec_row["decision_hash"],
                    "requirement_results": req_res_raw,
                    "rejection_reason": rejection_reason,
                    "created_at": dec_row["decided_at"],
                }

            # Assemble Founder UI checklist badges (✓ Supported, ? Unverified, ✕ Contradicted/Rejected)
            badges: List[Dict[str, str]] = []

            # 1. Platform badge
            plat_claim = claims_by_field.get("platform")
            plat_eval = req_eval_by_field.get("platform")
            if (plat_claim and plat_claim.get("status") == "CONTRADICTED") or (
                plat_eval and plat_eval.get("status") == "CONTRADICTED"
            ):
                badges.append({
                    "symbol": "✕",
                    "label": f"Platform Contradicted ({plat_claim.get('value') if plat_claim else 'Mismatch'})",
                    "status": "CONTRADICTED",
                    "field": "platform",
                })
            elif plat_claim and plat_claim.get("status") == "SUPPORTED" and plat_claim.get("value"):
                badges.append({
                    "symbol": "✓",
                    "label": str(plat_claim["value"]),
                    "status": "SUPPORTED",
                    "field": "platform",
                })
            else:
                # Check HIGH/MEDIUM evidence directly if claims not built yet
                plat_evs = [
                    e["extracted_value"]
                    for e in evidence_list
                    if e["supports_field"] == "platform" and e["confidence"] in ("HIGH", "MEDIUM")
                ]
                if len(set(v.lower() for v in plat_evs)) > 1:
                    badges.append({
                        "symbol": "✕",
                        "label": f"Platform Contradicted ({' vs '.join(sorted(set(plat_evs)))})",
                        "status": "CONTRADICTED",
                        "field": "platform",
                    })
                elif plat_evs:
                    badges.append({
                        "symbol": "✓",
                        "label": plat_evs[0],
                        "status": "SUPPORTED",
                        "field": "platform",
                    })

            # 2. Geography badge (e.g. India)
            domain_str = (c["canonical_domain"] or "").lower()
            if domain_str.endswith(".in") or domain_str.endswith(".co.in") or any(
                "india" in (e.get("raw_excerpt") or "").lower() or "country/in" in (e.get("raw_excerpt") or "").lower()
                for e in evidence_list
            ) or ("india" in prompt_lower and c["qualification_status"] in ("VERIFIED", "PROSPECT")):
                badges.append({
                    "symbol": "✓",
                    "label": "India",
                    "status": "SUPPORTED",
                    "field": "geography",
                })

            # 3. D2C / Storefront status badge
            sf_state = c["storefront_state"] or "unknown"
            http_st = c["http_status"]
            if sf_state == "active" and http_st == 200:
                badges.append({
                    "symbol": "✓",
                    "label": "D2C" if "d2c" in prompt_lower else "Active Storefront",
                    "status": "SUPPORTED",
                    "field": "storefront_state",
                })
            elif http_st in (401, 403, 429):
                badges.append({
                    "symbol": "?",
                    "label": f"HTTP {http_st} — Storefront Unconfirmed",
                    "status": "UNVERIFIED",
                    "field": "storefront_state",
                })
            elif sf_state in ("dead", "password_locked", "maintenance") or c["http_reachable"] == 0:
                badges.append({
                    "symbol": "✕",
                    "label": f"Storefront — {sf_state if c['http_reachable'] != 0 else 'Unreachable'}",
                    "status": "CONTRADICTED",
                    "field": "storefront_state",
                })

            # 4. Installed apps badge
            apps_claim = claims_by_field.get("installed_apps")
            if apps_claim and apps_claim.get("status") == "SUPPORTED" and apps_claim.get("value"):
                badges.append({
                    "symbol": "✓",
                    "label": f"Apps: {apps_claim['value']}",
                    "status": "SUPPORTED",
                    "field": "installed_apps",
                })

            # 5. Low-observability / unverified fields (Revenue, Paid App Subscription, Speed Audit)
            has_rev_req = any(r["field"] == "revenue" for r in requirements) or "revenue" in claims_by_field or any(
                w in prompt_lower for w in ("revenue", "turnover", "lakh", "crore", "arr", "mrr")
            )
            if has_rev_req:
                rev_cl = claims_by_field.get("revenue")
                if rev_cl and rev_cl.get("status") == "SUPPORTED" and rev_cl.get("value"):
                    badges.append({
                        "symbol": "✓",
                        "label": f"Revenue — {rev_cl['value']}",
                        "status": "SUPPORTED",
                        "field": "revenue",
                    })
                else:
                    badges.append({
                        "symbol": "?",
                        "label": "Revenue — UNVERIFIED",
                        "status": "UNVERIFIED",
                        "field": "revenue",
                    })

            has_paid_app_req = any(r["field"] == "paid_app_subscription" for r in requirements) or (
                "paid_app_subscription" in claims_by_field
                and any(w in prompt_lower for w in ("paid app", "paying", "subscription"))
            )
            if has_paid_app_req:
                badges.append({
                    "symbol": "?",
                    "label": "Paid App Billing — UNVERIFIED",
                    "status": "UNVERIFIED",
                    "field": "paid_app_subscription",
                })

            has_perf_req = any(r["field"] == "performance_audit" for r in requirements)
            if has_perf_req:
                badges.append({
                    "symbol": "?",
                    "label": "Page Speed — NOT_AUDITED",
                    "status": "NOT_AUDITED",
                    "field": "performance_audit",
                })

            # Build outreach draft preview for VERIFIED and PROSPECT candidates
            outreach_draft: Optional[Dict[str, Any]] = None
            if c["qualification_status"] in ("VERIFIED", "PROSPECT"):
                try:
                    from app.agents.maya.claim_validator import MayaClaimValidator
                    from app.agents.maya.outreach_composer import MayaOutreachComposer
                    from app.agents.schemas.session import ResearchSession
                    sess_obj = ResearchSession(
                        id=session_id,
                        task_id=task.id,
                        employee_id=sess_row["employee_id"],
                        raw_prompt=raw_prompt,
                        target_verified_leads=target_count,
                        current_hop=current_hop,
                        max_hops=max_hops,
                    )
                    val_res = MayaClaimValidator(session=sess_obj).validate(cid)
                    comp_res = MayaOutreachComposer().compose_deterministic(
                        validation_result=val_res,
                        company_name=c["company_name"],
                        canonical_domain=c["canonical_domain"],
                        qualification_result=c["qualification_status"],
                    )
                    outreach_draft = {
                        "to": str(comp_res.allowed_claims.get("contact") or f"contact@{c['canonical_domain']}"),
                        "subject": comp_res.subject,
                        "body": comp_res.body,
                        "allowed_claims": comp_res.allowed_claims,
                        "blocked_claims": val_res.low_obs_labels,
                    }
                except Exception:
                    outreach_draft = None

            candidates_payload.append({
                "id": cid,
                "company_name": c["company_name"],
                "canonical_domain": c["canonical_domain"],
                "initial_url": c["initial_url"],
                "final_url": c["final_url"],
                "discovery_hop": c["discovery_hop"],
                "http_reachable": bool(c["http_reachable"]) if c["http_reachable"] is not None else None,
                "http_status": c["http_status"],
                "page_available": bool(c["page_available"]) if c["page_available"] is not None else None,
                "storefront_state": sf_state,
                "audited_by_verifier": bool(c["audited_by_verifier"]),
                "qualification_status": c["qualification_status"],
                "rejection_reason": rejection_reason,
                "evidence_count": len(evidence_list),
                "claims_count": len(claims_list),
                "badges": badges,
                "evidence": evidence_list,
                "claims": claims_list,
                "decision": decision_dict,
                "outreach_draft": outreach_draft,
            })

        # Compute human-readable stage label matching Founder UI spec
        pending = task.pending_action or {}
        if task.status == "waiting_approval" or session_status == "waiting_approval":
            target_brand = pending.get("company_name") or (pending.get("tool_params") or {}).get("to") or "Lead"
            stage_label = f"APPROVAL REQUIRED → SEND_EMAIL ({target_brand})"
        elif session_status in ("verifying", "qualifying"):
            stage_label = f"VERIFY → Candidate {audited_count}/{max(total_candidates, 1)} (Hop {current_hop}/{max_hops})"
        elif session_status in ("discovering", "collecting"):
            stage_label = f"DISCOVER → Hop {current_hop}/{max_hops} ({total_candidates} Discovered)"
        elif session_status in ("composing", "validating"):
            stage_label = f"COMPOSE & VALIDATE → {metrics['verified'] + metrics['prospect']} Viable Candidates"
        elif task.status == "completed" or session_status in ("completed", "exhausted"):
            stage_label = f"VERIFY → Candidate {audited_count}/{total_candidates} (Hop {current_hop}/{max_hops} Complete)"
        else:
            stage_label = f"{session_status.upper()} → Candidate {audited_count}/{total_candidates}"

        pending_approval: Optional[Dict[str, Any]] = None
        if task.status == "waiting_approval" and pending:
            t_params = pending.get("tool_params") or {}
            pending_approval = {
                "required": True,
                "candidate_id": pending.get("candidate_id"),
                "company_name": pending.get("company_name") or t_params.get("to") or "Target Brand",
                "canonical_domain": pending.get("canonical_domain") or "",
                "action": pending.get("action") or (
                    "SEND_EMAIL" if pending.get("tool_name") == "email_sender" else str(pending.get("tool_name") or "ACTION").upper()
                ),
                "tool_name": pending.get("tool_name") or "email_sender",
                "permission": pending.get("permission") or "REQUEST",
                "reason": pending.get("reason") or "External side effect",
                "explanation": pending.get("explanation") or "",
                "to": str(t_params.get("to") or ""),
                "subject": str(t_params.get("subject") or ""),
                "body": str(t_params.get("body") or ""),
            }

        return {
            "task_id": task.id,
            "session_id": session_id,
            "employee_id": task.employee_id,
            "employee_name": task.employee_name,
            "task_status": task.status,
            "session_status": session_status,
            "raw_prompt": raw_prompt,
            "target_verified_leads": target_count,
            "current_hop": current_hop,
            "max_hops": max_hops,
            "termination_reason": sess_row["termination_reason"] or "",
            "current_stage_label": stage_label,
            "metrics": {
                "target": target_count,
                "candidates": total_candidates,
                "audited": audited_count,
                "verified": metrics["verified"],
                "prospects": metrics["prospect"],
                "rejected": metrics["rejected"],
                "pending": metrics["pending"],
            },
            "requirements": requirements,
            "candidates": candidates_payload,
            "pending_approval": pending_approval,
        }
    finally:
        conn.close()

