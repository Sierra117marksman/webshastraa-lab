from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
for p in (str(ROOT_DIR), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.db.connection import get_connection, wal_safe_backup
from backend.app.db.migrations import run_migrations
import backend.app.db.store as store
from app.models.memory import MemoryRecord
from app.models.employee import TaskRecord


def make_v1(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE employees (id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, employee_id TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, employee_id TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 3, data TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE permissions (employee_id TEXT NOT NULL, tool_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(employee_id, tool_id))")
    conn.execute("CREATE TABLE audit_log (id TEXT PRIMARY KEY, employee_id TEXT NOT NULL, task_id TEXT NOT NULL, event_type TEXT NOT NULL, timestamp TEXT NOT NULL, data TEXT NOT NULL)")

    employee = {
        "id": "emp_1", "name": "Maya Vance", "role": "SDR", "department": "CRM",
        "avatar_emoji": "🎯", "theme_color": "emerald", "objective": "Research",
        "persona": "Precise", "sops": ["Search"], "tools": ["web_search"],
        "schedule_type": "on_demand", "requires_approval_for": [], "status": "active",
        "created_at": "2026-09-27T08:00:00+00:00",
    }
    conn.execute("INSERT INTO employees VALUES (?, ?, ?, ?, ?)", ("emp_1", "Maya Vance", "CRM", json.dumps(employee), employee["created_at"]))

    task = {"id": "task_1", "employee_id": "emp_1", "employee_name": "Maya Vance", "task_prompt": "Find leads", "status": "completed", "steps": [], "final_output": "ok", "tokens_used": 12, "cost_usd": 0.01, "created_at": "2026-09-27T08:01:00+00:00", "completed_at": "2026-09-27T08:02:00+00:00"}
    conn.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?)", ("task_1", "emp_1", "completed", json.dumps(task), task["created_at"]))

    memory = {"id": "mem_1", "employee_id": "emp_1", "category": "learned_rule", "title": "Verify claims", "trigger_event": "manual_feedback", "scope": "lead_research", "source": "test", "context": "test", "critique": "test", "distilled_rule": "Verify before stating.", "confidence_score": 0.9, "priority": 2, "version": 1, "status": "active", "created_at": "2026-09-27T08:03:00+00:00"}
    conn.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?)", ("mem_1", "emp_1", "active", 2, json.dumps(memory), memory["created_at"]))

    permission = {"tool_id": "web_search", "permission": "EXECUTE", "requires_approval": False, "notes": None}
    conn.execute("INSERT INTO permissions VALUES (?, ?, ?)", ("emp_1", "web_search", json.dumps(permission)))

    audit = {"id": "audit_1", "employee_id": "emp_1", "task_id": "task_1", "event_type": "task_completed", "timestamp": "2026-09-27T08:02:00+00:00"}
    conn.execute("INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?)", ("audit_1", "emp_1", "task_1", "task_completed", audit["timestamp"], json.dumps(audit)))
    conn.commit()
    conn.close()


def test_fresh_database_creates_v2():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "fresh.db"
        run_migrations(str(path))
        conn = sqlite3.connect(path)
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert version == 2
        assert {"employees", "research_sessions", "candidates", "evidence", "claims", "qualification_decisions", "audit_log"}.issubset(tables)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.close()


def test_v1_migration_preserves_core_rows_and_creates_backup():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "legacy.db"
        make_v1(path)
        run_migrations(str(path))
        backup = Path(f"{path}.v1.bak")
        assert backup.exists()
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM permissions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
        conn.close()


def test_append_only_triggers():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "db.sqlite"
        run_migrations(str(path))
        conn = get_connection(str(path))
        now = "2026-09-27T08:00:00+00:00"
        conn.execute("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("e", "E", "R", "CRM", "O", "P", "[]", "on_demand", None, "active", 1, "{}", now))
        conn.execute("INSERT INTO tasks(id, employee_id, task_prompt, status, data, created_at) VALUES (?, ?, ?, ?, ?, ?)", ("t", "e", "T", "completed", "{}", now))
        conn.execute("INSERT INTO research_sessions(id, task_id, employee_id, raw_prompt, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("s", "t", "e", "x", "completed", now, now))
        conn.execute("INSERT INTO candidates(id, session_id, company_name, canonical_domain, initial_url, discovered_from_url, discovery_hop, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("c", "s", "C", "example.com", "https://example.com", "https://example.com", 1, now, now))
        conn.execute("INSERT INTO evidence(id, session_id, candidate_id, verifier_version, source_url, source_type, supports_field, signal_type, extracted_value, raw_excerpt, content_hash, confidence, retrieved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("ev", "s", "c", "v1", "https://example.com", "search_snippet", "platform", "search", "Shopify", "Shopify", "hash", "HIGH", now))
        conn.execute("INSERT INTO claims(id, session_id, candidate_id, field, value, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", ("cl", "s", "c", "platform", "Shopify", "SUPPORTED", now))
        conn.execute("INSERT INTO claim_evidence VALUES (?, ?, ?, ?)", ("cl", "ev", "s", "c"))
        conn.execute("INSERT INTO qualification_decisions(id, session_id, candidate_id, hop, result, decision_hash, claims_snapshot_json, requirement_results_json, supporting_claim_ids_json, supporting_evidence_ids_json, engine_version, notes_json, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("qd", "s", "c", 1, "VERIFIED", "dh", "{}", "{}", "[]", "[\"ev\"]", "v1", "[]", now))
        conn.commit()
        try:
            conn.execute("UPDATE evidence SET raw_excerpt='changed' WHERE id='ev'")
            raise AssertionError("Evidence update should have been blocked")
        except sqlite3.IntegrityError:
            pass
        try:
            conn.execute("DELETE FROM evidence WHERE id='ev'")
            raise AssertionError("Evidence delete should have been blocked")
        except sqlite3.IntegrityError:
            pass
        try:
            conn.execute("UPDATE qualification_decisions SET result='REJECTED' WHERE id='qd'")
            raise AssertionError("Qualification decision update should have been blocked")
        except sqlite3.IntegrityError:
            pass
        conn.close()


def test_store_repository_insert_update_and_metrics():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "repo.db"
        prev_db = store.DB_PATH
        try:
            store.DB_PATH = str(path)
            store.init_db()
            mem = MemoryRecord(
                id="mem_repo_1",
                employee_id="emp_sdr_01",
                category="learned_rule",
                title="Test Rule",
                trigger_event="founder_direct",
                scope="lead_research",
                source="test",
                context="ctx",
                critique="crit",
                distilled_rule="Rule v1",
                confidence_score=0.9,
                priority=1,
                version=1,
                status="proposed",
            )
            store.save_memory(mem)
            mem.status = "active"
            mem.activated_at = "2026-09-27T09:00:00+00:00"
            store.save_memory(mem)
            loaded = store.get_memory("mem_repo_1")
            assert loaded is not None and loaded.status == "active"
            assert loaded.activated_at == "2026-09-27T09:00:00+00:00"

            task = TaskRecord(
                id="task_repo_1",
                employee_id="emp_sdr_01",
                employee_name="Maya Vance",
                task_prompt="Find leads",
                status="running",
            )
            store.save_task(task)
            task.status = "completed"
            task.final_output = "done"
            store.save_task(task)
            loaded_task = store.get_task("task_repo_1")
            assert loaded_task is not None and loaded_task.status == "completed"
        finally:
            store.DB_PATH = prev_db


if __name__ == "__main__":
    test_fresh_database_creates_v2()
    test_v1_migration_preserves_core_rows_and_creates_backup()
    test_append_only_triggers()
    test_store_repository_insert_update_and_metrics()
    print("4 passed")
