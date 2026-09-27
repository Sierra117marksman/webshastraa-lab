from datetime import datetime
from typing import Any, List, Dict
from app.models.employee import AIEmployeeSpec, TaskRecord
from app.db.store import save_task
from app.tools.registry import execute_web_search
from app.engine.policy_engine import check_tool_permission
from app.agents.schemas.candidate import CandidateLedger
from app.agents.schemas.evidence import EvidenceStore
from app.agents.schemas.session import ResearchSession
from app.agents.employees.maya.planner import MayaPlanner
from app.agents.employees.maya.collector import MayaCollector
from app.agents.employees.maya.verifier import MayaFieldVerifier
from app.agents.employees.maya.qualifier import MayaQualifier
from app.agents.employees.maya.composer import MayaComposer
from app.agents.employees.maya.claim_validator import MayaClaimValidator


class MayaStateMachine:
    """
    Deterministic Python State Machine for Maya v2:
      PLAN -> [DISCOVER -> COLLECT -> VERIFY -> QUALIFY] (loop until target met or budget exhausted)
      -> COMPOSE -> VALIDATE -> OUTPUT.
    The LLM never controls state transitions or stopping decisions.
    """

    @classmethod
    def run(
        cls,
        employee: AIEmployeeSpec,
        record: TaskRecord,
        task_prompt: str,
        llm_client: Any = None
    ) -> TaskRecord:
        # 1. PLAN: Initialize ResearchSession, CandidateLedger, and EvidenceStore
        session: ResearchSession = MayaPlanner.create_session(record.id, task_prompt)
        ledger = CandidateLedger()
        evidence_store = EvidenceStore()

        step_num = 1
        record.steps.append({
            "step_number": step_num,
            "thought": (
                f"[State: PLAN] Initialized ResearchSession {session.id}. "
                f"Target Leads: {session.target_leads} | Hard Constraints: {session.hard_constraints} | "
                f"Max Hops: {session.max_hops}"
            ),
            "tool_called": "planner",
            "tool_input": session.hard_constraints,
            "tool_output": {
                "session_id": session.id,
                "target_leads": session.target_leads,
                "max_hops": session.max_hops
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        save_task(record)

        # 2. MULTI-HOP STATE LOOP: DISCOVER -> COLLECT -> VERIFY -> QUALIFY
        while session.should_continue_discovery(len(ledger.get_viable())):
            session.current_hop += 1
            hop = session.current_hop

            # ── STATE: DISCOVER ───────────────────────────────────────────────
            session.status = "discovering"
            queries = MayaPlanner.generate_hop_queries(session, hop)
            if not queries:
                session.termination_reason = f"No additional search queries remaining at Hop {hop}."
                break

            hop_results: List[Dict[str, Any]] = []
            for q in queries:
                policy = check_tool_permission(employee.id, "web_search", {"query": q}, record.id)
                if not policy.allowed:
                    record.status = "failed"
                    record.final_output = f"Policy block during DISCOVER: {policy.reason}"
                    record.completed_at = datetime.utcnow().isoformat()
                    save_task(record)
                    return record

                session.tavily_calls_made += 1
                res = execute_web_search(q, single_query=True)
                for item in res.get("results", []):
                    hop_results.append(item)

            # ── STATE: COLLECT ────────────────────────────────────────────────
            session.status = "collecting"
            new_candidates = MayaCollector.collect_from_search_results(
                search_results=hop_results,
                session=session,
                ledger=ledger,
                evidence_store=evidence_store,
                hop=hop,
                llm_client=llm_client
            )

            # ── STATE: VERIFY ─────────────────────────────────────────────────
            session.status = "verifying"
            unaudited = ledger.get_unaudited(limit=12)
            verified_in_hop = MayaFieldVerifier.verify_candidates(
                candidates=unaudited,
                session=session,
                evidence_store=evidence_store
            )

            # ── STATE: QUALIFY ────────────────────────────────────────────────
            session.status = "qualifying"
            MayaQualifier.qualify_ledger(
                ledger=ledger,
                session=session,
                evidence_store=evidence_store
            )

            viable_now = len(ledger.get_viable())
            verified_now = len(ledger.get_verified())
            prospects_now = len(ledger.get_prospects())
            rejected_now = len(ledger.get_rejected())

            step_num += 1
            record.steps.append({
                "step_number": step_num,
                "thought": (
                    f"[Hop {hop}/{session.max_hops}: DISCOVER → COLLECT → VERIFY → QUALIFY] "
                    f"Collected {len(new_candidates)} new candidates, mechanically audited {verified_in_hop} domains. "
                    f"Ledger Tally: {viable_now}/{session.target_leads} viable "
                    f"({verified_now} VERIFIED, {prospects_now} PROSPECT, {rejected_now} REJECTED)."
                ),
                "tool_called": "state_machine_hop",
                "tool_input": {"hop": hop, "queries": queries},
                "tool_output": {
                    "new_candidates": [c.canonical_domain for c in new_candidates],
                    "audited_in_hop": verified_in_hop,
                    "viable_total": viable_now,
                    "verified_total": verified_now,
                    "prospect_total": prospects_now,
                    "rejected_total": rejected_now,
                    "evidence_records": len(evidence_store.items)
                },
                "timestamp": datetime.utcnow().isoformat()
            })
            save_task(record)

            # Early stop check if a single hop yielded enough viable leads
            if viable_now >= session.target_leads:
                session.termination_reason = f"Target met ({viable_now}/{session.target_leads} viable leads)."
                break

        # 3. STATE: COMPOSE (Receives ONLY CandidateLedger + EvidenceStore, never raw search results)
        session.status = "composing"
        composed = MayaComposer.compose_deliverable(
            session=session,
            ledger=ledger,
            evidence_store=evidence_store,
            llm_client=llm_client
        )

        # 4. STATE: VALIDATE (Verify every supported claim & sanitize outreach)
        session.status = "validating"
        final_markdown = composed["markdown"]
        validation_notes: List[str] = []
        for cand in ledger.get_viable():
            final_markdown, was_repaired, violations = MayaClaimValidator.validate_and_repair_text(
                final_markdown, cand
            )
            if was_repaired:
                validation_notes.extend(violations)

        if session.status != "exhausted":
            session.status = "completed"

        step_num += 1
        record.steps.append({
            "step_number": step_num,
            "thought": (
                f"[State: COMPOSE → VALIDATE → FINISH] "
                f"Composed deliverable from {composed['viable_count']} viable candidates "
                f"and {len(evidence_store.items)} primary Evidence records. "
                f"Termination: {session.termination_reason}"
            ),
            "tool_called": "claim_validator",
            "tool_input": {"viable_candidates": composed["viable_count"]},
            "tool_output": {
                "session_status": session.status,
                "termination_reason": session.termination_reason,
                "validation_repairs": validation_notes,
                "llm_calls_made": session.llm_calls_made,
                "tavily_calls_made": session.tavily_calls_made
            },
            "timestamp": datetime.utcnow().isoformat()
        })

        record.final_output = final_markdown
        record.tokens_used = session.tokens_in + session.tokens_out
        # Calculate cost from actual measured LLM tokens and Tavily searches
        llm_cost = (session.tokens_in * 0.000000075) + (session.tokens_out * 0.0000003)
        tavily_cost = session.tavily_calls_made * 0.005
        record.cost_usd = round(max(0.0004, llm_cost + tavily_cost), 5)
        record.status = "completed"
        record.completed_at = datetime.utcnow().isoformat()
        save_task(record)
        return record
