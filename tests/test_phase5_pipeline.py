"""Phase 5 Pipeline Tests — isolated SQLite databases, mocked LLM/Verifier.

Tests:
 1. TaskStateMachine: hop budget enforcement (hop > max_hops raises)
 2. TaskStateMachine: transition to discovering increments current_hop
 3. TaskStateMachine: waiting_approval resume locked via resume_from_approval(task)
 4. MayaCollector: deduplicates by canonical domain (second insertion skipped)
 5. MayaCollector: domains_seen prevents cross-hop re-registration
 6. MayaVerifier: evidence immutability — SQLite BEFORE UPDATE trigger aborts update
 7. MayaQualifier: decision_hash idempotency — second qualify_candidate returns existing
 8. MayaQualifier: LOW_PUBLIC_OBSERVABILITY field → PROSPECT not REJECTED
 9. MayaClaimValidator: HIGH confidence + non-empty excerpt → allowed_outreach_claims
10. MayaClaimValidator: LOW confidence → blocked, not in whitelist
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import sys
import tempfile
import traceback
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup — must run with PYTHONPATH=backend
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))



# ---------------------------------------------------------------------------
# Shared isolated DB helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _isolated_db():
    """Create a temporary SQLite DB with the full v2 schema and monkeypatch all DB_PATH globals."""
    import app.db.connection as conn_mod
    import app.db.store as store_mod

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    original_conn_path = conn_mod.DB_PATH
    original_store_path = store_mod.DB_PATH

    conn_mod.DB_PATH = db_path
    store_mod.DB_PATH = db_path

    try:
        from app.db.migrations import run_migrations
        run_migrations(db_path)
        yield db_path
    finally:
        conn_mod.DB_PATH = original_conn_path
        store_mod.DB_PATH = original_store_path
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _make_session(session_id: str = "sess_test01", task_id: str = "task_test01") -> Any:
    """Create a ResearchSession with sensible test defaults."""
    from app.agents.schemas.session import ResearchSession
    return ResearchSession(
        id=session_id,
        task_id=task_id,
        employee_id="emp_test",
        raw_prompt="Find 5 Shopify stores in India selling apparel",
        target_verified_leads=5,
        max_hops=3,
    )


def _insert_session_row(db_path: str, session: Any) -> None:
    """Insert a minimal research_sessions row so FK constraints pass."""
    import app.db.connection as conn_mod
    original = conn_mod.DB_PATH
    conn_mod.DB_PATH = db_path
    # We need a tasks row first (research_sessions has FK to tasks)
    try:
        from app.db.connection import transaction
        # Insert a minimal tasks row
        with transaction(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO employees
                (id, name, role, department, objective, persona, sops_json, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session.employee_id, "Test Employee", "SDR", "Sales",
                 "Test objective", "Test persona", "[]",
                 json.dumps({"id": session.employee_id, "name": "Test Employee",
                             "role": "SDR", "department": "Sales",
                             "objective": "test", "persona": "test", "sops": [],
                             "tools": [], "created_at": session.created_at}),
                 session.created_at),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO tasks (id, employee_id, task_prompt, status, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session.task_id, session.employee_id, session.raw_prompt, "running",
                 json.dumps({"id": session.task_id, "employee_id": session.employee_id,
                             "task_prompt": session.raw_prompt, "status": "running",
                             "steps": [], "tokens_used": 0, "cost_usd": 0.0,
                             "created_at": session.created_at}),
                 session.created_at),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO research_sessions (
                    id, task_id, employee_id, raw_prompt, status,
                    target_verified_leads, current_hop, max_hops,
                    search_queries_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id, session.task_id, session.employee_id,
                    session.raw_prompt, session.status,
                    session.target_verified_leads, session.current_hop, session.max_hops,
                    "[]",
                    session.created_at, session.updated_at,
                ),
            )
    finally:
        conn_mod.DB_PATH = original


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

PASS = "[PASS]"
FAIL = "[FAIL]"
_results: list[tuple[str, bool, str]] = []



def _test(name: str):
    def decorator(fn):
        def wrapper():
            try:
                fn()
                _results.append((name, True, ""))
                print(f"  {PASS} {name}")
            except Exception as exc:
                tb = traceback.format_exc()
                _results.append((name, False, str(exc)))
                print(f"  {FAIL} {name}: {exc}")
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# TEST 1: Hop budget enforcement — transition to discovering beyond max_hops raises
# ---------------------------------------------------------------------------

@_test("TaskStateMachine: hop budget → InvalidStateTransitionError beyond max_hops")
def test_hop_budget_enforcement():
    from app.agents.schemas.session import InvalidStateTransitionError
    from app.agents.core.task_state_machine import TaskStateMachine

    with _isolated_db() as db_path:
        # Patch DB_PATH in task_state_machine
        import app.agents.core.task_state_machine as tsm_mod
        orig = tsm_mod
        session = _make_session()
        session.max_hops = 2
        _insert_session_row(db_path, session)

        machine = TaskStateMachine(session=session, task_id="task_t1")

        import app.db.connection as conn_mod
        old_path = conn_mod.DB_PATH
        conn_mod.DB_PATH = db_path
        try:
            # Hop 1
            machine.transition("discovering")
            assert session.current_hop == 1, f"Expected hop=1, got {session.current_hop}"
            machine.transition("collecting")
            machine.transition("verifying")
            machine.transition("qualifying")
            # Hop 2
            machine.transition("discovering")
            assert session.current_hop == 2, f"Expected hop=2, got {session.current_hop}"
            machine.transition("collecting")
            machine.transition("verifying")
            machine.transition("qualifying")
            # Hop 3 — should raise because max_hops=2
            raised = False
            try:
                machine.transition("discovering")
            except InvalidStateTransitionError:
                raised = True
            assert raised, "Expected InvalidStateTransitionError on hop 3 when max_hops=2"
        finally:
            conn_mod.DB_PATH = old_path


# ---------------------------------------------------------------------------
# TEST 2: current_hop increments correctly
# ---------------------------------------------------------------------------

@_test("TaskStateMachine: current_hop increments on discovering transitions")
def test_current_hop_increments():
    from app.agents.core.task_state_machine import TaskStateMachine

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path
        session = _make_session()
        _insert_session_row(db_path, session)
        machine = TaskStateMachine(session=session, task_id="task_t2")

        assert session.current_hop == 0
        machine.transition("discovering")
        assert session.current_hop == 1
        machine.transition("collecting")
        machine.transition("verifying")
        machine.transition("qualifying")
        machine.transition("discovering")
        assert session.current_hop == 2


# ---------------------------------------------------------------------------
# TEST 3: waiting_approval resume locked
# ---------------------------------------------------------------------------

@_test("TaskStateMachine: resume_from_approval locked — reads task.resume_state only")
def test_approval_resume_locked():
    from app.agents.schemas.session import InvalidStateTransitionError
    from app.agents.core.task_state_machine import TaskStateMachine

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path
        session = _make_session()
        _insert_session_row(db_path, session)
        machine = TaskStateMachine(session=session, task_id="task_t3")

        # Navigate to validating → waiting_approval
        machine.transition("discovering")
        machine.transition("collecting")
        machine.transition("verifying")
        machine.transition("qualifying")
        machine.transition("composing")
        machine.transition("validating")
        machine.transition("waiting_approval")

        assert session.status == "waiting_approval"

        # resume_from_approval must fail if task has no resume_state
        raised = False
        try:
            task = MagicMock()
            task.resume_state = None
            machine.resume_from_approval(task)
        except InvalidStateTransitionError:
            raised = True
        assert raised, "Expected InvalidStateTransitionError with no resume_state"

        # resume_from_approval with valid resume_state
        task2 = MagicMock()
        task2.resume_state = "composing"
        result = machine.resume_from_approval(task2)
        assert result == "composing", f"Expected composing, got {result}"


# ---------------------------------------------------------------------------
# TEST 4: Collector — deduplicates by canonical domain
# ---------------------------------------------------------------------------

@_test("MayaCollector: canonical domain deduplication (second insertion skipped)")
def test_collector_deduplication():
    from app.agents.maya.collector import MayaCollector

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        _insert_session_row(db_path, session)
        collector = MayaCollector(session=session, db_path=db_path)

        results = [
            {"url": "https://www.example-store.com/products", "title": "Example Store", "content": "Shopify apparel store"},
            {"url": "https://example-store.com", "title": "Example Store Mirror", "content": "Same store different URL"},
        ]
        inserted = collector.register_from_search_results(results, hop=1)
        assert len(inserted) == 1, f"Expected 1 unique candidate, got {len(inserted)}"


# ---------------------------------------------------------------------------
# TEST 5: Collector — domains_seen prevents cross-hop re-registration
# ---------------------------------------------------------------------------

@_test("MayaCollector: domains_seen blocks re-registration in second hop")
def test_collector_domains_seen():
    from app.agents.maya.collector import MayaCollector

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        _insert_session_row(db_path, session)
        collector = MayaCollector(session=session, db_path=db_path)

        results_hop1 = [{"url": "https://hopstore.in", "title": "Hop Store", "content": "apparel"}]
        inserted1 = collector.register_from_search_results(results_hop1, hop=1)
        assert len(inserted1) == 1

        # Same domain in hop 2
        results_hop2 = [{"url": "https://hopstore.in/collections", "title": "Hop Store", "content": "same"}]
        inserted2 = collector.register_from_search_results(results_hop2, hop=2)
        assert len(inserted2) == 0, f"Expected 0 re-registered, got {len(inserted2)}"


# ---------------------------------------------------------------------------
# TEST 6: Evidence immutability — BEFORE UPDATE trigger aborts update
# ---------------------------------------------------------------------------

@_test("Evidence immutability: SQLite BEFORE UPDATE trigger aborts direct UPDATE")
def test_evidence_immutability():
    with _isolated_db() as db_path:
        _now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # employees
            conn.execute("""
                INSERT OR IGNORE INTO employees
                (id, name, role, department, objective, persona, sops_json, data, created_at)
                VALUES ('emp_ev', 'EV Employee', 'SDR', 'Sales', 'obj', 'persona', '[]',
                        '{"id":"emp_ev","name":"EV","role":"SDR","department":"Sales","objective":"","persona":"","sops":[],"tools":[],"created_at":"2026-01-01"}', '2026-01-01')
            """)

            # tasks
            conn.execute("""
                INSERT OR IGNORE INTO tasks (id, employee_id, task_prompt, status, data, created_at)
                VALUES ('task_ev', 'emp_ev', 'test', 'running',
                        '{"id":"task_ev","employee_id":"emp_ev","task_prompt":"test","status":"running","steps":[],"tokens_used":0,"cost_usd":0.0,"created_at":"2026-01-01"}', '2026-01-01')
            """)
            # research_sessions — correct schema (no data column)
            conn.execute("""
                INSERT OR IGNORE INTO research_sessions
                (id, task_id, employee_id, raw_prompt, status, target_verified_leads,
                 current_hop, max_hops, search_queries_json, created_at, updated_at)
                VALUES ('sess_ev_test', 'task_ev', 'emp_ev', 'test', 'verifying', 5, 1, 4, '[]',
                        datetime('now'), datetime('now'))
            """)
            # candidates — correct schema (no snippet_context, no data)
            conn.execute("""
                INSERT OR IGNORE INTO candidates
                (id, session_id, company_name, canonical_domain, initial_url,
                 discovered_from_url, discovery_hop, created_at, updated_at)
                VALUES ('C_ev1', 'sess_ev_test', 'EVTest', 'evtest.com', 'https://evtest.com',
                        'https://source.com', 1, datetime('now'), datetime('now'))
            """)
            # evidence — correct schema (no data, has retrieved_at NOT NULL)
            conn.execute("""
                INSERT INTO evidence
                (id, session_id, candidate_id, verifier_version, source_url, source_type,
                 supports_field, signal_type, extracted_value, raw_excerpt,
                 confidence, content_hash, retrieved_at)
                VALUES ('E_imm1', 'sess_ev_test', 'C_ev1', 'v2.0', 'https://evtest.com',
                        'live_html_footprint', 'platform', 'html_tag', 'Shopify',
                        'cdn.shopify.com present in source', 'HIGH', 'hash_imm_001', datetime('now'))
            """)
            conn.commit()

            # Attempt to UPDATE — should be aborted by trigger
            raised = False
            try:
                conn.execute("UPDATE evidence SET extracted_value='TAMPERED' WHERE id='E_imm1'")
                conn.commit()
            except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
                if "immutable" in str(exc).lower() or "append-only" in str(exc).lower() or "forbidden" in str(exc).lower():
                    raised = True
                else:
                    raise
            assert raised, "Expected immutability trigger to abort UPDATE on evidence"

            # Attempt to DELETE — should also be aborted by trigger
            delete_raised = False
            try:
                conn.execute("DELETE FROM evidence WHERE id='E_imm1'")
                conn.commit()
            except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
                if "append-only" in str(exc).lower() or "forbidden" in str(exc).lower():
                    delete_raised = True
                else:
                    raise
            assert delete_raised, "Expected immutability trigger to abort DELETE on evidence"
        finally:
            conn.close()




# ---------------------------------------------------------------------------
# TEST 7: Qualifier — decision_hash idempotency
# ---------------------------------------------------------------------------

@_test("MayaQualifier: decision_hash idempotency — second qualify returns existing")
def test_qualifier_idempotency():
    from app.agents.maya.qualifier import MayaQualifier
    from app.agents.schemas.requirement import Requirement

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        session.current_hop = 1  # hop must be >= 1 for QualificationDecision
        _insert_session_row(db_path, session)

        # Insert a candidate
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT OR IGNORE INTO candidates
            (id, session_id, company_name, canonical_domain, initial_url,
             discovered_from_url, discovery_hop, created_at, updated_at)
            VALUES ('C_idm1', ?, 'IDM Store', 'idmstore.com', 'https://idmstore.com',
                    'https://s.com', 1, datetime('now'), datetime('now'))
        """, (session.id,))
        conn.commit()
        conn.close()


        req = Requirement(field="platform", operator="exists", expected=True)
        qualifier = MayaQualifier(session=session, requirements=[req], db_path=db_path)

        decision1 = qualifier.qualify_candidate("C_idm1")
        decision2 = qualifier.qualify_candidate("C_idm1")

        assert decision1 is not None
        assert decision2 is not None
        assert decision1.decision_hash == decision2.decision_hash, (
            f"Expected same hash: {decision1.decision_hash} vs {decision2.decision_hash}"
        )


# ---------------------------------------------------------------------------
# TEST 8: LOW_PUBLIC_OBSERVABILITY → PROSPECT not REJECTED
# ---------------------------------------------------------------------------

@_test("MayaQualifier: LOW_PUBLIC_OBSERVABILITY field unverified → PROSPECT not REJECTED")
def test_low_obs_field_prospect():
    from app.agents.maya.qualifier import MayaQualifier
    from app.agents.schemas.requirement import Requirement

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        session.current_hop = 1
        _insert_session_row(db_path, session)

        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT OR IGNORE INTO candidates
            (id, session_id, company_name, canonical_domain, initial_url,
             discovered_from_url, discovery_hop, created_at, updated_at)
            VALUES ('C_obs1', ?, 'Obs Store', 'obsstore.com', 'https://obsstore.com',
                    'https://s.com', 1, datetime('now'), datetime('now'))
        """, (session.id,))
        conn.commit()
        conn.close()


        # Revenue is a LOW_PUBLIC_OBSERVABILITY HARD requirement — no evidence should → PROSPECT
        req = Requirement(field="revenue", operator="range", expected={"min_value": 1000000}, priority="HARD")
        assert req.observability_class == "LOW_PUBLIC_OBSERVABILITY"
        assert req.on_unknown == "PROSPECT"

        qualifier = MayaQualifier(session=session, requirements=[req], db_path=db_path)
        decision = qualifier.qualify_candidate("C_obs1")
        assert decision is not None
        assert decision.result == "PROSPECT", (
            f"Expected PROSPECT for unverified LOW_PUBLIC_OBSERVABILITY field, got {decision.result}"
        )


# ---------------------------------------------------------------------------
# TEST 9: ClaimValidator — HIGH confidence + non-empty excerpt → allowed
# ---------------------------------------------------------------------------

@_test("MayaClaimValidator: HIGH confidence + excerpt → allowed_outreach_claims")
def test_claim_validator_allowed():
    from app.agents.maya.claim_validator import MayaClaimValidator

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        _insert_session_row(db_path, session)

        # Insert candidate and evidence
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT OR IGNORE INTO candidates
            (id, session_id, company_name, canonical_domain, initial_url,
             discovered_from_url, discovery_hop, created_at, updated_at)
            VALUES ('C_cv1', ?, 'CV Store', 'cvstore.com', 'https://cvstore.com',
                    'https://s.com', 1, datetime('now'), datetime('now'))
        """, (session.id,))
        conn.execute("""
            INSERT OR IGNORE INTO evidence
            (id, session_id, candidate_id, verifier_version, source_url, source_type,
             supports_field, signal_type, extracted_value, raw_excerpt,
             confidence, content_hash, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            "E_cv1", session.id, "C_cv1",
            "v2.0", "https://cvstore.com", "live_html_footprint",
            "platform", "html_tag", "Shopify",
            "cdn.shopify.com found in <script src>", "HIGH", "hash_cv1",
        ))
        conn.commit()
        conn.close()

        validator = MayaClaimValidator(session=session, db_path=db_path)
        result = validator.validate("C_cv1")
        assert result.has_any_allowed_claim, "Expected at least one allowed claim"
        fields = [c.field for c in result.allowed_outreach_claims]
        assert "platform" in fields, f"Expected 'platform' in allowed claims, got {fields}"


# ---------------------------------------------------------------------------
# TEST 10: ClaimValidator — LOW confidence → blocked
# ---------------------------------------------------------------------------

@_test("MayaClaimValidator: LOW confidence evidence → blocked, not in whitelist")
def test_claim_validator_low_confidence_blocked():
    from app.agents.maya.claim_validator import MayaClaimValidator

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        _insert_session_row(db_path, session)

        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT OR IGNORE INTO candidates
            (id, session_id, company_name, canonical_domain, initial_url,
             discovered_from_url, discovery_hop, created_at, updated_at)
            VALUES ('C_low1', ?, 'Low Store', 'lowstore.com', 'https://lowstore.com',
                    'https://s.com', 1, datetime('now'), datetime('now'))
        """, (session.id,))
        conn.execute("""
            INSERT OR IGNORE INTO evidence
            (id, session_id, candidate_id, verifier_version, source_url, source_type,
             supports_field, signal_type, extracted_value, raw_excerpt,
             confidence, content_hash, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            "E_low1", session.id, "C_low1",
            "v2.0", "https://lowstore.com", "search_snippet",
            "platform", "text_mention", "WooCommerce",
            "website powered by WooCommerce (text-only mention)", "LOW", "hash_low1",
        ))
        conn.commit()
        conn.close()


        validator = MayaClaimValidator(session=session, db_path=db_path)
        result = validator.validate("C_low1")
        assert not result.has_any_allowed_claim, (
            "Expected NO allowed claims for LOW confidence evidence"
        )
        assert "platform" in result.blocked_fields, (
            f"Expected 'platform' in blocked_fields, got {result.blocked_fields}"
        )


# ---------------------------------------------------------------------------
# TEST 11: MayaPlanner fail-closed requirement normalization
# ---------------------------------------------------------------------------

@_test("MayaPlanner: fail-closed overrides LLM REJECT on LOW_PUBLIC_OBSERVABILITY fields")
def test_planner_fail_closed_normalization():
    from app.agents.maya.planner import MayaPlanner, _PlanSchema, _RawRequirement

    with _isolated_db() as db_path:
        import app.db.connection as conn_mod
        conn_mod.DB_PATH = db_path

        session = _make_session()
        _insert_session_row(db_path, session)

        mock_gw = MagicMock()
        mock_res = MagicMock()
        mock_res.parsed_result = _PlanSchema(
            search_queries=["shopify stores india"],
            requirements=[
                _RawRequirement(field="platform", operator="equals", expected="Shopify", priority="HARD", on_unknown="REJECT"),
                _RawRequirement(field="revenue", operator="range", expected={"min": 1000000}, priority="HARD", on_unknown="REJECT", observability_class="HIGH"),
                _RawRequirement(field="paid_app_subscription", operator="exists", expected=True, priority="HARD", on_unknown="REJECT", observability_class="HIGH"),
                _RawRequirement(field="nonexistent_garbage_field", operator="equals", expected="foo"),
            ],
            target_verified_leads=5,
            max_hops=3,
        )
        mock_gw.call.return_value = mock_res

        planner = MayaPlanner(gateway=mock_gw, db_path=db_path)
        plan_result = planner.plan("Find 5 Shopify stores in India with 10L revenue paying in apps", session.id)

        req_by_field = {r.field: r for r in plan_result.requirements}
        assert "nonexistent_garbage_field" not in req_by_field, "Unknown field must be dropped"
        assert req_by_field["revenue"].observability_class == "LOW_PUBLIC_OBSERVABILITY"
        assert req_by_field["revenue"].on_unknown == "PROSPECT"
        assert req_by_field["paid_app_subscription"].observability_class == "LOW_PUBLIC_OBSERVABILITY"
        assert req_by_field["paid_app_subscription"].on_unknown == "PROSPECT"
        assert len(plan_result.observability_notices) >= 2


# ---------------------------------------------------------------------------
# TEST 12: Composite FK cross-candidate evidence rejection & candidate sync guard
# ---------------------------------------------------------------------------

@_test("SQLite Invariants: composite FK rejects cross-candidate evidence & guard blocks direct status tamper")
def test_composite_fk_and_candidate_sync_guard():
    with _isolated_db() as db_path:
        session = _make_session()
        _insert_session_row(db_path, session)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # Insert Candidate 1 and Candidate 2
            for cid, dom in [("C_fk1", "fk1.com"), ("C_fk2", "fk2.com")]:
                conn.execute(
                    """
                    INSERT INTO candidates
                    (id, session_id, company_name, canonical_domain, initial_url,
                     discovered_from_url, discovery_hop, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'https://s.com', 1, datetime('now'), datetime('now'))
                    """,
                    (cid, session.id, cid, dom, f"https://{dom}"),
                )
            # Insert Evidence belonging to Candidate 1
            conn.execute(
                """
                INSERT INTO evidence
                (id, session_id, candidate_id, verifier_version, source_url, source_type,
                 supports_field, signal_type, extracted_value, raw_excerpt,
                 confidence, content_hash, retrieved_at)
                VALUES ('E_fk1', ?, 'C_fk1', 'v2.0', 'https://fk1.com', 'live_html_footprint',
                        'platform', 'html_tag', 'Shopify', 'cdn.shopify.com', 'HIGH', 'h_fk1', datetime('now'))
                """,
                (session.id,),
            )
            # Insert Claim belonging to Candidate 2
            conn.execute(
                """
                INSERT INTO claims
                (id, session_id, candidate_id, field, value, status, version, updated_at)
                VALUES ('clm_fk2', ?, 'C_fk2', 'platform', 'Shopify', 'SUPPORTED', 1, datetime('now'))
                """,
                (session.id,),
            )
            conn.commit()

            # Attempt to bind Candidate 1's evidence (E_fk1) to Candidate 2's claim (clm_fk2)
            fk_rejected = False
            try:
                conn.execute(
                    """
                    INSERT INTO claim_evidence (claim_id, evidence_id, session_id, candidate_id)
                    VALUES ('clm_fk2', 'E_fk1', ?, 'C_fk2')
                    """,
                    (session.id,),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                fk_rejected = True
            assert fk_rejected, "Composite FK must reject binding C_fk1 evidence to C_fk2 claim"

            # Attempt to directly set candidates.qualification_status='VERIFIED' without latest_decision_id
            guard_rejected = False
            try:
                conn.execute("UPDATE candidates SET qualification_status='VERIFIED' WHERE id='C_fk1'")
                conn.commit()
            except (sqlite3.IntegrityError, sqlite3.OperationalError):
                guard_rejected = True
            assert guard_rejected, "trg_candidates_guard_qualification_update must block unbacked status update"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main():
    print("\n=== Phase 5 Pipeline Tests ===\n")

    test_hop_budget_enforcement()
    test_current_hop_increments()
    test_approval_resume_locked()
    test_collector_deduplication()
    test_collector_domains_seen()
    test_evidence_immutability()
    test_qualifier_idempotency()
    test_low_obs_field_prospect()
    test_claim_validator_allowed()
    test_claim_validator_low_confidence_blocked()
    test_planner_fail_closed_normalization()
    test_composite_fk_and_candidate_sync_guard()

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)

    print(f"\n{'='*40}")
    print(f"Phase 5 Pipeline:  {passed}/{total} passed")
    if failed:
        print(f"\nFailed tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"  [FAIL] {name}: {err}")
    print(f"{'='*40}\n")

    sys.exit(0 if failed == 0 else 1)



if __name__ == "__main__":
    main()
