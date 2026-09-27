"""Maya v2 Agent Runtime — thin dispatcher replacing runner.py.

Architecture:
    HTTP endpoint → agent_runtime.run_employee_task()
                  → ResearchSession + TaskStateMachine + ContextBuilder
                  → PLAN → DISCOVER → COLLECT → VERIFY → QUALIFY
                  → (enough verified → COMPOSE | hop budget left → DISCOVER again)
                  → VALIDATE → APPROVAL / DELIVERY

The Python state machine owns the loop. The LLM never decides when to stop.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.agents.core.task_state_machine import TaskStateMachine
from app.agents.maya.claim_validator import MayaClaimValidator
from app.agents.maya.collector import MayaCollector
from app.agents.maya.outreach_composer import MayaOutreachComposer, OutreachResult
from app.agents.maya.planner import MayaPlanner, PlanResult
from app.agents.maya.qualifier import MayaQualifier
from app.agents.maya.verifier import MayaVerifier
from app.agents.schemas.session import ResearchSession
from app.db.connection import DB_PATH, get_connection, transaction
from app.db.store import (
    get_employee,
    get_session_metrics,
    get_task,
    save_audit_log,
    save_memory,
    save_task,
)
from app.engine.context_builder import ContextBuilder
from app.engine.llm_gateway import LLMGateway
from app.engine.policy_engine import check_tool_permission
from app.models.employee import AIEmployeeSpec, TaskRecord
from app.models.memory import AuditLogEntry
from app.tools.registry import execute_tool_call

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_audit(
    employee_id: str,
    task_id: str,
    event_type: str,
    *,
    session_id: Optional[str] = None,
    context_snapshot_id: Optional[str] = None,
    memories_used: Optional[List[str]] = None,
    tools_called: Optional[List[str]] = None,
    decision: Optional[str] = None,
    output_summary: str = "",
    founder_feedback: Optional[str] = None,
    cost_usd: float = 0.0,
    tokens_used: int = 0,
) -> None:
    """Write an append-only audit log entry safely."""
    try:
        entry = AuditLogEntry(
            id=f"audit_{uuid.uuid4().hex[:12]}",
            employee_id=employee_id,
            task_id=task_id,
            session_id=session_id,
            context_snapshot_id=context_snapshot_id,
            event_type=event_type,  # type: ignore[arg-type]
            memories_used=memories_used or [],
            tools_called=tools_called or [],
            decision=decision,
            output_summary=(output_summary or "")[:500],
            founder_feedback=founder_feedback,
            cost_usd=cost_usd,
            tokens_used=tokens_used,
            timestamp=_utc_now(),
        )
        save_audit_log(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AgentRuntime] Audit log write failed: %s", exc)


def _create_session(session: ResearchSession, db_path: Optional[str] = None) -> None:
    """Persist a new ResearchSession row into research_sessions."""
    import app.db.connection as _conn_mod
    target_db = db_path or _conn_mod.DB_PATH
    try:
        with transaction(target_db) as conn:

            conn.execute(
                """
                INSERT OR IGNORE INTO research_sessions (
                    id, task_id, employee_id, raw_prompt, status,
                    target_verified_leads, current_hop, max_hops,
                    search_queries_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.task_id,
                    session.employee_id,
                    session.raw_prompt[:2000],
                    session.status,
                    session.target_verified_leads,
                    session.current_hop,
                    session.max_hops,
                    json.dumps(session.search_queries_used or []),
                    session.created_at,
                    session.updated_at,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AgentRuntime] Failed to persist session %s: %s", session.id, exc)


def _update_task_status(
    record: TaskRecord,
    status: str,
    final_output: Optional[str] = None,
) -> None:
    record.status = status  # type: ignore[assignment]
    if final_output is not None:
        record.final_output = final_output
    if status in ("completed", "failed", "waiting_approval", "rejected", "needs_clarification"):
        record.completed_at = _utc_now()
    save_task(record)


def run_employee_task(employee: AIEmployeeSpec, task_prompt: str) -> TaskRecord:
    """Dispatch an employee task.

    SDR/Sales/CRM research tasks execute the Maya v2 deterministic state machine.
    Other departments or direct single-tool actions delegate to the general runner.
    """
    dep_upper = (employee.department or "").upper()
    is_direct_email_only = (
        "@" in task_prompt
        and any(w in task_prompt.lower() for w in ("send email to", "email to"))
    )
    if not (("CRM" in dep_upper or "SALES" in dep_upper or "SDR" in dep_upper) and not is_direct_email_only):
        from app.engine.runner import run_employee_task as _legacy_run_employee_task
        return _legacy_run_employee_task(employee, task_prompt)

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    session_id = f"sess_{uuid.uuid4().hex[:12]}"

    record = TaskRecord(
        id=task_id,
        employee_id=employee.id,
        employee_name=employee.name,
        session_id=session_id,
        task_prompt=task_prompt,
        status="running",
        steps=[],
        tokens_used=0,
        cost_usd=0.0,
        time_saved_mins=30,
    )
    save_task(record)

    policy = check_tool_permission(employee.id, "web_search", {"query": task_prompt[:120]}, task_id)
    if not policy.allowed:
        _update_task_status(record, "failed", f"Policy block: {policy.reason}")
        return record

    session = ResearchSession(
        id=session_id,
        task_id=task_id,
        employee_id=employee.id,
        raw_prompt=task_prompt,
        target_verified_leads=10,
        max_hops=4,
    )
    _create_session(session)

    machine = TaskStateMachine(session=session, task_id=task_id)
    gateway = LLMGateway()

    try:
        final_output = _run_pipeline(
            session=session,
            machine=machine,
            gateway=gateway,
            employee=employee,
            record=record,
            task_prompt=task_prompt,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[AgentRuntime][task=%s] Unexpected error: %s", task_id, exc, exc_info=True)
        _update_task_status(record, "failed", f"Runtime error: {exc}")
        return record

    if record.status == "waiting_approval":
        save_task(record)
        return record

    final_task_status = "needs_clarification" if session.status == "needs_clarification" else (
        "failed" if session.status == "failed" else "completed"
    )
    _update_task_status(record, final_task_status, final_output)
    return record


def resume_approved_task(
    task_id: str,
    approved: bool,
    founder_feedback: Optional[str] = None,
) -> TaskRecord:
    """Resume a waiting_approval task with locked resume_from_approval(task) semantics."""
    record = get_task(task_id)
    if not record or record.status != "waiting_approval":
        return record  # type: ignore[return-value]

    pending = record.pending_action or {}
    session_id = record.session_id or pending.get("session_id")

    if not approved:
        record.status = "rejected"
        record.final_output = f"Action rejected by founder. Feedback: {founder_feedback or 'No feedback given.'}"
        record.completed_at = _utc_now()
        save_task(record)

        if session_id:
            session_data = _load_session_data(session_id)
            if session_data and session_data.get("status") == "waiting_approval":
                sess = ResearchSession(**session_data)
                tsm = TaskStateMachine(session=sess, task_id=task_id)
                tsm.transition("rejected", reason="Rejected by founder")

        if founder_feedback and founder_feedback.strip():
            try:
                from app.engine.reflector import generate_proposed_memory
                emp = get_employee(record.employee_id)
                if emp:
                    proposed = generate_proposed_memory(
                        employee_id=emp.id,
                        employee_name=emp.name,
                        employee_role=emp.role,
                        task_id=task_id,
                        task_prompt=record.task_prompt,
                        what_happened=str(record.pending_action or "Pending tool action"),
                        feedback=founder_feedback,
                        trigger_event="rejection",
                    )
                    if proposed:
                        save_memory(proposed)
                        _log_audit(
                            employee_id=record.employee_id,
                            task_id=task_id,
                            session_id=session_id,
                            event_type="reflection_proposed",
                            decision=f"Proposed memory: {proposed.id}",
                            output_summary=proposed.distilled_rule[:200],
                            founder_feedback=founder_feedback,
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AgentRuntime] Reflection failed on rejection: %s", exc)

        _log_audit(
            employee_id=record.employee_id,
            task_id=task_id,
            session_id=session_id,
            event_type="approval_rejected",
            decision="Rejected",
            founder_feedback=founder_feedback,
            output_summary=(record.final_output or "")[:200],
        )
        return record

    # Approved: execute any pending tool action after authoritative PolicyEngine check
    tool_name = pending.get("tool_name")
    tool_params = pending.get("tool_params") or {}
    tool_result_data: Any = None

    if tool_name:
        policy = check_tool_permission(record.employee_id, tool_name, tool_params, task_id)
        if not policy.allowed:
            record.status = "failed"
            record.final_output = f"Post-approval policy block: {policy.reason}"
            record.completed_at = _utc_now()
            save_task(record)
            return record

        tool_result_data = execute_tool_call(tool_name, tool_params)
        record.steps.append({
            "step_number": len(record.steps) + 1,
            "thought": f"Approved by Founder. Executing {tool_name}.",
            "tool_called": tool_name,
            "tool_input": tool_params,
            "tool_output": tool_result_data,
        })

    if not session_id:
        record.status = "completed"
        if tool_name:
            record.final_output = f"Successfully executed {tool_name} after founder sign-off: {json.dumps(tool_result_data)}"
        else:
            record.final_output = "Approved. Task completed."
        record.completed_at = _utc_now()
        record.pending_action = None
        save_task(record)
        _log_audit(
            employee_id=record.employee_id,
            task_id=task_id,
            event_type="approval_granted",
            tools_called=[tool_name] if tool_name else [],
            decision="Approved and executed",
            founder_feedback=founder_feedback,
            output_summary=(record.final_output or "")[:200],
        )
        return record

    # Session-backed task: resume strictly via locked resume_from_approval(record)
    session_data = _load_session_data(session_id)
    if not session_data:
        record.status = "failed"
        record.final_output = "Cannot resume: session data not found."
        record.completed_at = _utc_now()
        save_task(record)
        return record

    session = ResearchSession(**session_data)
    machine = TaskStateMachine(session=session, task_id=task_id)

    # Locked resume: destination comes exclusively from record.resume_state
    resumed_state = machine.resume_from_approval(record)
    record.pending_action = None

    _log_audit(
        employee_id=record.employee_id,
        task_id=task_id,
        session_id=session_id,
        event_type="approval_granted",
        tools_called=[tool_name] if tool_name else [],
        decision=f"Resumed session to locked state '{resumed_state}'",
        founder_feedback=founder_feedback,
        output_summary=f"Resumed session {session_id} -> {resumed_state}",
    )

    if resumed_state == "completed":
        existing_out = record.final_output or "Approved and completed."
        if tool_name and tool_result_data is not None:
            to_recipient = tool_params.get("to", "recipient")
            existing_out = (
                f"{existing_out}\n\n---\n"
                f"### ✅ Approved Outreach Executed\n"
                f"- **Action:** `SEND_EMAIL` (`{tool_name}`)\n"
                f"- **Recipient:** `{to_recipient}`\n"
                f"- **Result:** `{json.dumps(tool_result_data)}`"
            )
        _update_task_status(record, "completed", existing_out)
        return record

    employee = get_employee(record.employee_id)
    if not employee:
        _update_task_status(record, "failed", "Cannot resume: employee not found.")
        return record

    gateway = LLMGateway()
    try:
        final_output = _run_pipeline(
            session=session,
            machine=machine,
            gateway=gateway,
            employee=employee,
            record=record,
            task_prompt=record.task_prompt,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[AgentRuntime] Resume error for task=%s: %s", task_id, exc, exc_info=True)
        _update_task_status(record, "failed", f"Resume error: {exc}")
        return record

    _update_task_status(record, "completed", final_output)
    return record


def _wants_outreach_send(task_prompt: str) -> bool:
    lower = (task_prompt or "").lower()
    return any(
        phrase in lower
        for phrase in (
            "send outreach",
            "send cold outreach",
            "send cold email",
            "send cold emails",
            "send email",
            "send emails",
        )
    )


def _run_pipeline(
    session: ResearchSession,
    machine: TaskStateMachine,
    gateway: LLMGateway,
    employee: AIEmployeeSpec,
    record: TaskRecord,
    task_prompt: str,
) -> str:
    """PLAN → (DISCOVER → COLLECT → VERIFY → QUALIFY)* → COMPOSE → VALIDATE → output."""
    planner = MayaPlanner(gateway=gateway)
    collector = MayaCollector(session=session)
    verifier = MayaVerifier(session=session)
    composer = MayaOutreachComposer(gateway=gateway)

    plan: Optional[PlanResult] = None

    # ── PLAN ──────────────────────────────────────────────────────────────────
    if session.status == "planning":
        ContextBuilder.build(
            employee=employee,
            stage="PLAN",
            task_id=record.id,
            session_id=session.id,
            task_scope="lead_research",
            stage_input={"task_prompt": task_prompt},
        )
        plan = planner.plan(task_prompt, session.id)
        session.requirements = plan.requirements
        session.max_hops = plan.max_hops
        session.target_verified_leads = plan.target_verified_leads

        if not plan.requirements and not plan.search_queries:
            machine.transition("needs_clarification", reason="No plan produced")
            return "Task requires clarification: could not generate a research plan."

        record.steps.append({
            "step_number": len(record.steps) + 1,
            "thought": (
                f"[State: PLAN] Compiled {len(plan.requirements)} requirements "
                f"(target={session.target_verified_leads}, max_hops={session.max_hops})."
            ),
            "tool_called": "planner",
            "tool_input": {"task_prompt": task_prompt[:200]},
            "tool_output": {
                "session_id": session.id,
                "requirements": [r.field for r in plan.requirements],
                "observability_notices": plan.observability_notices,
            },
            "timestamp": _utc_now(),
        })
        save_task(record)
        machine.transition("discovering", reason="PLAN complete")

    # ── DISCOVER → COLLECT → VERIFY → QUALIFY loop ───────────────────────────
    while session.status == "discovering":
        hop = session.current_hop
        if hop == 1 and plan and plan.search_queries:
            queries = [q for q in plan.search_queries if q not in session.search_queries_used]
            session.search_queries_used.extend(queries)
        else:
            queries = MayaPlanner.generate_hop_queries(session, hop)

        if not queries:
            queries = [task_prompt[:200]]

        all_search_results: List[Dict[str, Any]] = []
        for query in queries:
            policy = check_tool_permission(employee.id, "web_search", {"query": query}, record.id)
            if not policy.allowed:
                machine.transition("failed", reason=f"Policy block on web_search: {policy.reason}")
                return f"Policy block during DISCOVER: {policy.reason}"

            from app.services.search_service import search_web
            session.tavily_calls_made = (session.tavily_calls_made or 0) + 1
            result = search_web(query=query)
            if result.status == "success":
                hits = result.data.get("results", []) if isinstance(result.data, dict) else []
                all_search_results.extend(hits)

        # ── COLLECT ───────────────────────────────────────────────────────────
        machine.transition("collecting", reason=f"Search complete: {len(all_search_results)} results")
        new_ids = collector.register_from_search_results(
            all_search_results, hop=hop
        )

        # ── VERIFY ────────────────────────────────────────────────────────────
        machine.transition("verifying", reason=f"{len(new_ids)} new candidates collected")
        unaudited = collector.get_unaudited_candidates(limit=15)
        verifier.verify_batch(unaudited)

        # ── QUALIFY ───────────────────────────────────────────────────────────
        machine.transition("qualifying", reason="Verification complete")
        qualifier = MayaQualifier(
            session=session,
            requirements=session.requirements or [],
        )
        audited_ids = [c["id"] for c in unaudited]
        qualifier.qualify_batch(audited_ids)

        metrics = get_session_metrics(session.id)
        record.steps.append({
            "step_number": len(record.steps) + 1,
            "thought": (
                f"[Hop {hop}/{session.max_hops}] Collected {len(new_ids)} candidates, "
                f"audited {len(audited_ids)} domains. "
                f"Tally: {metrics.get('verified', 0)} VERIFIED, "
                f"{metrics.get('prospect', 0)} PROSPECT, "
                f"{metrics.get('rejected', 0)} REJECTED."
            ),
            "tool_called": "state_machine_hop",
            "tool_input": {"hop": hop, "queries": queries},
            "tool_output": metrics,
            "timestamp": _utc_now(),
        })
        save_task(record)

        # ── Deterministic Python termination check ────────────────────────────
        if machine.should_continue_discovery():
            try:
                machine.transition("discovering", reason="Insufficient verified leads — next hop")
            except Exception:  # noqa: BLE001
                machine.transition("exhausted", reason="Max hops reached")
                break
        else:
            if session.status != "exhausted":
                machine.transition("composing", reason="Target met or discovery complete")
            break

    # ── EXHAUSTED → composing or completed ───────────────────────────────────
    if session.status == "exhausted":
        metrics = get_session_metrics(session.id)
        viable = metrics.get("verified", 0) + metrics.get("prospect", 0)
        if viable == 0:
            machine.transition("completed", reason="Exhausted with 0 viable leads")
            return (
                f"# Maya v2 Research Deliverable\n\n"
                f"Research exhausted after {session.current_hop}/{session.max_hops} hops. "
                f"No viable leads survived mechanical verification. {session.termination_reason or ''}"
            )
        machine.transition("composing", reason="Compose best-effort from viable leads after exhaustion")

    # ── COMPOSE ───────────────────────────────────────────────────────────────
    if session.status == "composing":
        ContextBuilder.build(
            employee=employee,
            stage="COMPOSE",
            task_id=record.id,
            session_id=session.id,
            task_scope="cold_outreach",
            stage_input={"session_id": session.id, "task_prompt": task_prompt[:500]},
        )
        deliverable, outreach_results = _compose_deliverable_with_results(
            session=session,
            composer=composer,
            task_prompt=task_prompt,
            observability_notices=plan.observability_notices if plan else [],
        )
        machine.transition("validating", reason="Composition complete")

        repaired_deliverable, _, _ = MayaClaimValidator.validate_and_repair_text(deliverable)
        if not repaired_deliverable or len(repaired_deliverable.strip()) < 20:
            machine.transition("failed", reason="Empty deliverable")
            return "Task failed: outreach composer produced no valid output."

        # If prompt explicitly requests sending outreach/emails, enforce PolicyEngine approval gate
        if _wants_outreach_send(task_prompt) and outreach_results:
            primary = outreach_results[0]
            recipient_email = str(
                primary.allowed_claims.get("contact") or f"contact@{primary.canonical_domain}"
            )
            email_params = {
                "to": recipient_email,
                "subject": primary.subject,
                "body": primary.body,
            }
            policy = check_tool_permission(employee.id, "email_sender", email_params, record.id)
            if policy.allowed and policy.requires_approval:
                record.resume_state = "completed"
                record.status = "waiting_approval"
                record.final_output = repaired_deliverable
                record.pending_action = {
                    "action": "SEND_EMAIL",
                    "tool_name": "email_sender",
                    "permission": "REQUEST",
                    "reason": "External side effect",
                    "candidate_id": primary.candidate_id,
                    "company_name": primary.company_name,
                    "canonical_domain": primary.canonical_domain,
                    "tool_params": email_params,
                    "explanation": (
                        f"Maya wants to send outreach to {primary.company_name} "
                        f"({primary.canonical_domain})"
                    ),
                }
                machine.transition(
                    "waiting_approval",
                    reason=f"Outreach email to {primary.company_name} requires founder approval",
                )
                save_task(record)
                return repaired_deliverable

        machine.transition("completed", reason="Deliverable validated")
        return repaired_deliverable

    return f"Research session ended in state '{session.status}'. {session.termination_reason or ''}"


def _compose_deliverable(
    session: ResearchSession,
    composer: MayaOutreachComposer,
    task_prompt: str,
    observability_notices: Optional[List[str]] = None,
) -> str:
    """Pull viable candidates, validate claims, compose outreach, return markdown deliverable."""
    deliverable, _ = _compose_deliverable_with_results(
        session=session,
        composer=composer,
        task_prompt=task_prompt,
        observability_notices=observability_notices,
    )
    return deliverable


def _compose_deliverable_with_results(
    session: ResearchSession,
    composer: MayaOutreachComposer,
    task_prompt: str,
    observability_notices: Optional[List[str]] = None,
) -> tuple[str, List[OutreachResult]]:
    """Pull viable candidates, validate claims, compose outreach, return (markdown, outreach_results)."""
    import app.db.connection as _conn_mod
    conn = get_connection(_conn_mod.DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT id, canonical_domain, company_name, qualification_status
            FROM candidates
            WHERE session_id=? AND qualification_status IN ('VERIFIED', 'PROSPECT')
            ORDER BY
                CASE qualification_status WHEN 'VERIFIED' THEN 0 ELSE 1 END ASC,
                rowid ASC
            LIMIT ?
            """,
            (session.id, session.target_verified_leads),
        ).fetchall()
        viable_candidates = [dict(r) for r in rows]
    finally:
        conn.close()

    if not viable_candidates:
        return "# Maya v2 Research Deliverable\n\nNo viable leads found to compose outreach for.", []

    validator = MayaClaimValidator(session=session)
    outreach_results: List[OutreachResult] = []

    for cand in viable_candidates:
        validation = validator.validate(cand["id"])
        result = composer.compose(
            validation_result=validation,
            company_name=cand["company_name"],
            canonical_domain=cand["canonical_domain"],
            qualification_result=cand["qualification_status"],
            task_prompt=task_prompt,
        )
        outreach_results.append(result)

    verified = [r for r in outreach_results if r.qualification_result == "VERIFIED"]
    prospects = [r for r in outreach_results if r.qualification_result == "PROSPECT"]

    lines = [
        "# Maya v2 Research Deliverable",
        "",
        f"**Session:** `{session.id}`  ",
        f"**Hops completed:** {session.current_hop}/{session.max_hops}  ",
        f"**Verified leads:** {len(verified)}  ",
        f"**Prospects:** {len(prospects)}  ",
        "",
    ]

    if len(outreach_results) < session.target_verified_leads:
        lines.append(
            f"> **Epistemic Honesty Notice:** Requested **{session.target_verified_leads}** leads; "
            f"after exhausting **{session.current_hop}/{session.max_hops}** hops, only "
            f"**{len(outreach_results)}** genuine candidate(s) survived mechanical verification. "
            f"Zero filler leads were fabricated."
        )
        lines.append("")

    if observability_notices:
        lines.append("> **Observability Notice:**")
        for notice in observability_notices:
            lines.append(f"> - {notice}")
        lines.append("")

    lines.extend(["---", ""])

    if verified:
        lines.append("## ✅ VERIFIED LEADS")
        lines.append("")
        for r in verified:
            lines.append(r.to_markdown())

    if prospects:
        lines.append("## 🟡 PROSPECTS (Needs Qualification)")
        lines.append("")
        for r in prospects:
            lines.append(r.to_markdown())

    return "\n".join(lines), outreach_results


def request_candidate_outreach_approval(
    task_id: str,
    candidate_id: str,
    recipient_email: Optional[str] = None,
    custom_subject: Optional[str] = None,
    custom_body: Optional[str] = None,
) -> Optional[TaskRecord]:
    """Queue a validated outreach email for a specific candidate into waiting_approval."""
    import app.db.connection as _conn_mod
    record = get_task(task_id)
    if not record or not record.session_id:
        return None

    session_data = _load_session_data(record.session_id)
    if not session_data:
        return None

    conn = get_connection(_conn_mod.DB_PATH)
    try:
        cand_row = conn.execute(
            """
            SELECT id, company_name, canonical_domain, qualification_status
            FROM candidates
            WHERE id=? AND session_id=?
            """,
            (candidate_id, record.session_id),
        ).fetchone()
    finally:
        conn.close()

    if not cand_row:
        return None

    session = ResearchSession(**session_data)
    validator = MayaClaimValidator(session=session)
    validation = validator.validate(candidate_id)

    # Use deterministic template (or custom subject/body validated against whitelist)
    composer = MayaOutreachComposer(gateway=LLMGateway())
    composed = composer.compose_deterministic(
        validation_result=validation,
        company_name=cand_row["company_name"],
        canonical_domain=cand_row["canonical_domain"],
        qualification_result=cand_row["qualification_status"],
    )

    to_addr = (
        (recipient_email or "").strip()
        or str(composed.allowed_claims.get("contact") or f"contact@{cand_row['canonical_domain']}")
    )
    subj = (custom_subject or "").strip() or composed.subject
    body_text = (custom_body or "").strip() or composed.body
    body_text, _, _ = MayaClaimValidator.validate_and_repair_text(body_text)

    email_params = {"to": to_addr, "subject": subj, "body": body_text}
    policy = check_tool_permission(record.employee_id, "email_sender", email_params, record.id)
    if not policy.allowed:
        raise ValueError(f"Policy Engine blocked outreach request: {policy.reason}")

    machine = TaskStateMachine(session=session, task_id=record.id)
    if session.status != "waiting_approval":
        machine.transition(
            "waiting_approval",
            reason=f"Outreach email to {cand_row['company_name']} queued for founder approval",
        )

    record.resume_state = "completed"
    record.status = "waiting_approval"
    record.pending_action = {
        "action": "SEND_EMAIL",
        "tool_name": "email_sender",
        "permission": "REQUEST",
        "reason": "External side effect",
        "candidate_id": cand_row["id"],
        "company_name": cand_row["company_name"],
        "canonical_domain": cand_row["canonical_domain"],
        "tool_params": email_params,
        "explanation": f"Maya wants to send outreach to {cand_row['company_name']} ({cand_row['canonical_domain']})",
    }
    save_task(record)
    return record


def _load_session_data(session_id: str) -> Optional[Dict[str, Any]]:
    import app.db.connection as _conn_mod
    conn = get_connection(_conn_mod.DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT id, task_id, employee_id, raw_prompt, status,
                   target_verified_leads, current_hop, max_hops,
                   search_queries_json, termination_reason, created_at, updated_at
            FROM research_sessions WHERE id=?
            """,
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "employee_id": row["employee_id"],
            "raw_prompt": row["raw_prompt"],
            "status": row["status"],
            "target_verified_leads": row["target_verified_leads"],
            "current_hop": row["current_hop"],
            "max_hops": row["max_hops"],
            "search_queries_used": json.loads(row["search_queries_json"] or "[]"),
            "termination_reason": row["termination_reason"] or "",
        }
    finally:
        conn.close()

