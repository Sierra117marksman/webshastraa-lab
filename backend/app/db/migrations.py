"""Versioned SQLite schema and safe v1 -> v2 migration."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .connection import DB_PATH, MigrationError, get_connection, wal_safe_backup

SCHEMA_VERSION = 2

ALLOWED_TASK_STATUSES = {
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "rejected",
    "needs_clarification",
}

ALLOWED_MEMORY_CATEGORIES = {
    "mistake_avoided",
    "learned_rule",
    "proven_playbook",
    "founder_preference",
}
ALLOWED_MEMORY_STATUS = {"proposed", "active", "superseded", "rejected"}
ALLOWED_MEMORY_SCOPES = {
    "global",
    "cold_outreach",
    "lead_research",
    "hiring_research",
    "enterprise_clients",
    "financial_ops",
    "content_creation",
}


V2_CORE_TABLES = {
    "employees",
    "permissions",
    "memories",
    "tasks",
    "audit_log",
}


V2_SCHEMA_SQL = r"""
CREATE TABLE employees (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    department TEXT NOT NULL,
    objective TEXT NOT NULL,
    persona TEXT NOT NULL,
    sops_json TEXT NOT NULL,
    schedule_type TEXT NOT NULL DEFAULT 'on_demand',
    schedule_interval_mins INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    config_version INTEGER NOT NULL DEFAULT 1 CHECK (config_version >= 1),
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE permissions (
    employee_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('READ', 'ANALYZE', 'DRAFT', 'REQUEST', 'EXECUTE')),
    requires_approval INTEGER NOT NULL DEFAULT 0 CHECK (requires_approval IN (0, 1)),
    notes TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (employee_id, tool_id),
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('mistake_avoided', 'learned_rule', 'proven_playbook', 'founder_preference')),
    scope TEXT NOT NULL CHECK (scope IN ('global', 'cold_outreach', 'lead_research', 'hiring_research', 'enterprise_clients', 'financial_ops', 'content_creation')),
    applies_to_stages_json TEXT NOT NULL DEFAULT '["PLAN", "COMPOSE"]',
    rule_key TEXT NOT NULL,
    title TEXT NOT NULL,
    distilled_rule TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'superseded', 'rejected')),
    priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0.0 AND 1.0),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    supersedes TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (supersedes) REFERENCES memories(id) ON DELETE SET NULL
);
CREATE INDEX idx_memories_emp_status_scope ON memories(employee_id, status, scope, priority ASC, created_at DESC);
CREATE INDEX idx_memories_emp_rule_key ON memories(employee_id, rule_key, status);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    session_id TEXT,
    task_prompt TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'waiting_approval', 'completed', 'failed', 'rejected', 'needs_clarification')),
    resume_state TEXT CHECK (resume_state IS NULL OR resume_state IN ('discovering', 'collecting', 'verifying', 'qualifying', 'composing', 'validating', 'completed')),
    pending_action_json TEXT,
    final_output TEXT,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

CREATE TABLE research_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    employee_id TEXT NOT NULL,
    raw_prompt TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'planning', 'discovering', 'collecting', 'verifying',
        'qualifying', 'composing', 'validating', 'waiting_approval',
        'completed', 'exhausted', 'failed', 'needs_clarification'
    )),
    target_verified_leads INTEGER NOT NULL DEFAULT 10 CHECK (target_verified_leads >= 1),
    allow_prospects INTEGER NOT NULL DEFAULT 1 CHECK (allow_prospects IN (0, 1)),
    current_hop INTEGER NOT NULL DEFAULT 0 CHECK (current_hop >= 0),
    max_hops INTEGER NOT NULL DEFAULT 4 CHECK (max_hops >= 1),
    max_candidates INTEGER NOT NULL DEFAULT 50 CHECK (max_candidates >= 1),
    max_verification_requests INTEGER NOT NULL DEFAULT 50 CHECK (max_verification_requests >= 1),
    verification_requests_made INTEGER NOT NULL DEFAULT 0 CHECK (verification_requests_made >= 0),
    search_queries_json TEXT NOT NULL DEFAULT '[]',
    termination_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

CREATE TABLE session_requirements (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN (
        'platform', 'installed_apps', 'paid_app_subscription', 'd2c_status',
        'revenue', 'technical_observables', 'performance_audit', 'geography',
        'storefront_state', 'contact', 'hiring_role'
    )),
    operator TEXT NOT NULL CHECK (operator IN ('equals', 'in', 'contains_any', 'range', 'exists')),
    expected_json TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('HARD', 'SOFT')),
    on_unknown TEXT NOT NULL CHECK (on_unknown IN ('REJECT', 'PROSPECT')),
    observability_class TEXT NOT NULL DEFAULT 'HIGH' CHECK (observability_class IN ('HIGH', 'MEDIUM', 'LOW_PUBLIC_OBSERVABILITY')),
    evidence_required INTEGER NOT NULL DEFAULT 1 CHECK (evidence_required IN (0, 1)),
    allowed_source_types_json TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
);

CREATE TABLE candidates (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    canonical_domain TEXT NOT NULL,
    initial_url TEXT NOT NULL,
    final_url TEXT,
    discovered_from_url TEXT NOT NULL,
    discovery_hop INTEGER NOT NULL,
    http_reachable INTEGER,
    http_status INTEGER,
    page_available INTEGER,
    storefront_state TEXT NOT NULL DEFAULT 'unknown' CHECK (storefront_state IN ('active', 'password_locked', 'maintenance', 'dead', 'unknown')),
    audited_by_verifier INTEGER NOT NULL DEFAULT 0 CHECK (audited_by_verifier IN (0, 1)),
    qualification_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (qualification_status IN ('PENDING', 'VERIFIED', 'PROSPECT', 'REJECTED')),
    latest_decision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, canonical_domain),
    UNIQUE(id, session_id),
    FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
);
CREATE INDEX idx_candidates_session_status ON candidates(session_id, qualification_status);

CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    verifier_version TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'live_http_headers', 'live_html_footprint', 'storeleads_directory',
        'annual_filing', 'official_financial_report', 'official_company_page',
        'job_board', 'search_snippet'
    )),
    supports_field TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    extracted_value TEXT NOT NULL,
    raw_excerpt TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    financial_period TEXT,
    retrieved_at TEXT NOT NULL,
    UNIQUE(id, session_id, candidate_id),
    FOREIGN KEY (candidate_id, session_id) REFERENCES candidates(id, session_id) ON DELETE RESTRICT
);
CREATE INDEX idx_evidence_candidate_field ON evidence(candidate_id, supports_field);

CREATE TRIGGER trg_evidence_no_update
BEFORE UPDATE ON evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence table is strictly append-only: UPDATE is forbidden');
END;

CREATE TRIGGER trg_evidence_no_delete
BEFORE DELETE ON evidence
BEGIN
    SELECT RAISE(ABORT, 'evidence table is strictly append-only: DELETE is forbidden');
END;

CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    field TEXT NOT NULL CHECK (field IN (
        'identity', 'website', 'platform', 'installed_apps', 'paid_app_subscription',
        'd2c_status', 'revenue', 'technical_observables', 'performance_audit', 'contact'
    )),
    value TEXT,
    status TEXT NOT NULL CHECK (status IN ('SUPPORTED', 'UNSUPPORTED', 'CONTRADICTED', 'UNVERIFIED', 'NOT_AUDITED')),
    notes TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_id, field),
    UNIQUE(id, session_id, candidate_id),
    FOREIGN KEY (candidate_id, session_id) REFERENCES candidates(id, session_id) ON DELETE CASCADE
);

CREATE TABLE claim_evidence (
    claim_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    PRIMARY KEY (claim_id, evidence_id),
    FOREIGN KEY (claim_id, session_id, candidate_id) REFERENCES claims(id, session_id, candidate_id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id, session_id, candidate_id) REFERENCES evidence(id, session_id, candidate_id) ON DELETE RESTRICT
);

CREATE TABLE qualification_decisions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    hop INTEGER NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('VERIFIED', 'PROSPECT', 'REJECTED')),
    decision_hash TEXT NOT NULL UNIQUE,
    claims_snapshot_json TEXT NOT NULL,
    requirement_results_json TEXT NOT NULL,
    supporting_claim_ids_json TEXT NOT NULL,
    supporting_evidence_ids_json TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    notes_json TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id, session_id) REFERENCES candidates(id, session_id) ON DELETE RESTRICT
);
CREATE INDEX idx_qual_decisions_candidate ON qualification_decisions(candidate_id, decided_at DESC);

CREATE TRIGGER trg_qual_decisions_no_update
BEFORE UPDATE ON qualification_decisions
BEGIN
    SELECT RAISE(ABORT, 'qualification_decisions table is strictly append-only: UPDATE is forbidden');
END;

CREATE TRIGGER trg_qual_decisions_no_delete
BEFORE DELETE ON qualification_decisions
BEGIN
    SELECT RAISE(ABORT, 'qualification_decisions table is strictly append-only: DELETE is forbidden');
END;

CREATE TRIGGER trg_candidates_guard_qualification_update
BEFORE UPDATE OF qualification_status, latest_decision_id ON candidates
WHEN NEW.qualification_status != 'PENDING'
BEGIN
    SELECT CASE
        WHEN NEW.latest_decision_id IS NULL THEN
            RAISE(ABORT, 'Cannot set candidate qualification_status without latest_decision_id')
        WHEN (SELECT result FROM qualification_decisions WHERE id = NEW.latest_decision_id AND candidate_id = NEW.id AND session_id = NEW.session_id) IS NULL THEN
            RAISE(ABORT, 'latest_decision_id does not reference a valid QualificationDecision for this candidate')
        WHEN (SELECT result FROM qualification_decisions WHERE id = NEW.latest_decision_id) != NEW.qualification_status THEN
            RAISE(ABORT, 'candidate.qualification_status must match qualification_decisions.result')
    END;
END;

CREATE TRIGGER trg_sync_candidate_on_decision_insert
AFTER INSERT ON qualification_decisions
BEGIN
    UPDATE candidates
    SET latest_decision_id = NEW.id,
        qualification_status = NEW.result,
        updated_at = NEW.decided_at
    WHERE id = NEW.candidate_id AND session_id = NEW.session_id;
END;

CREATE TABLE context_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('PLAN', 'COLLECT', 'VERIFY', 'QUALIFY', 'COMPOSE', 'REFLECT')),
    model TEXT NOT NULL,
    memory_ids_json TEXT NOT NULL,
    allowed_tools_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id) ON DELETE CASCADE
);

CREATE TABLE audit_log (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    session_id TEXT,
    context_snapshot_id TEXT,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX idx_audit_task_time ON audit_log(task_id, timestamp DESC);

CREATE TRIGGER trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is strictly append-only: UPDATE is forbidden');
END;

CREATE TRIGGER trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is strictly append-only: DELETE is forbidden');
END;
"""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _load_json(raw: str, context: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MigrationError(f"Invalid JSON in {context}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"Expected object JSON in {context}")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _rule_key(category: str, scope: str, title: str) -> str:
    material = f"{category}|{scope}|{title.strip().casefold()}".encode("utf-8")
    return "memory:" + hashlib.sha256(material).hexdigest()[:24]


def _normalize_scope(scope: Any) -> str:
    candidate = str(scope or "global").strip()
    return candidate if candidate in ALLOWED_MEMORY_SCOPES else "global"


def _normalize_task_status(status: Any) -> str:
    candidate = str(status or "pending")
    if candidate not in ALLOWED_TASK_STATUSES:
        raise MigrationError(f"Unsupported legacy task status: {candidate!r}")
    return candidate


def _create_v2_core_table(conn: sqlite3.Connection, table: str) -> None:
    """Create a renamed version of one existing v1 core table."""
    ddl = {
        "employees": """
            CREATE TABLE employees_v2 (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT NOT NULL,
                objective TEXT NOT NULL,
                persona TEXT NOT NULL,
                sops_json TEXT NOT NULL,
                schedule_type TEXT NOT NULL DEFAULT 'on_demand',
                schedule_interval_mins INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                config_version INTEGER NOT NULL DEFAULT 1 CHECK (config_version >= 1),
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """,
        "permissions": """
            CREATE TABLE permissions_v2 (
                employee_id TEXT NOT NULL,
                tool_id TEXT NOT NULL,
                permission TEXT NOT NULL CHECK (permission IN ('READ', 'ANALYZE', 'DRAFT', 'REQUEST', 'EXECUTE')),
                requires_approval INTEGER NOT NULL DEFAULT 0 CHECK (requires_approval IN (0, 1)),
                notes TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (employee_id, tool_id),
                FOREIGN KEY (employee_id) REFERENCES employees_v2(id) ON DELETE CASCADE
            )
        """,
        "memories": """
            CREATE TABLE memories_v2 (
                id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category IN ('mistake_avoided', 'learned_rule', 'proven_playbook', 'founder_preference')),
                scope TEXT NOT NULL CHECK (scope IN ('global', 'cold_outreach', 'lead_research', 'hiring_research', 'enterprise_clients', 'financial_ops', 'content_creation')),
                applies_to_stages_json TEXT NOT NULL DEFAULT '[\"PLAN\", \"COMPOSE\"]',
                rule_key TEXT NOT NULL,
                title TEXT NOT NULL,
                distilled_rule TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'superseded', 'rejected')),
                priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
                confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0.0 AND 1.0),
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                supersedes TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                activated_at TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees_v2(id) ON DELETE CASCADE,
                FOREIGN KEY (supersedes) REFERENCES memories_v2(id) ON DELETE SET NULL
            )
        """,
        "tasks": """
            CREATE TABLE tasks_v2 (
                id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                session_id TEXT,
                task_prompt TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'waiting_approval', 'completed', 'failed', 'rejected', 'needs_clarification')),
                resume_state TEXT CHECK (resume_state IS NULL OR resume_state IN ('discovering', 'collecting', 'verifying', 'qualifying', 'composing', 'validating', 'completed')),
                pending_action_json TEXT,
                final_output TEXT,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees_v2(id) ON DELETE CASCADE
            )
        """,
        "audit_log": """
            CREATE TABLE audit_log_v2 (
                id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                session_id TEXT,
                context_snapshot_id TEXT,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """,
    }
    conn.execute(ddl[table])


def _migrate_employees(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, name, department, data, created_at FROM employees").fetchall()
    for row in rows:
        data = _load_json(row["data"], f"employees/{row['id']}")
        conn.execute(
            """
            INSERT INTO employees_v2 (
                id, name, role, department, objective, persona, sops_json,
                schedule_type, schedule_interval_mins, status, config_version, data, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                data.get("name", row["name"]),
                data.get("role", "Autonomous Agent"),
                data.get("department", row["department"]),
                data.get("objective", ""),
                data.get("persona", ""),
                json.dumps(data.get("sops", []), ensure_ascii=False),
                data.get("schedule_type", "on_demand"),
                data.get("schedule_interval_mins"),
                data.get("status", "active"),
                int(data.get("config_version", 1)),
                row["data"],
                row["created_at"],
            ),
        )


def _migrate_permissions(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT employee_id, tool_id, data FROM permissions").fetchall()
    employee_ids = {r[0] for r in conn.execute("SELECT id FROM employees_v2")}
    for row in rows:
        data = _load_json(row["data"], f"permissions/{row['employee_id']}:{row['tool_id']}")
        if row["employee_id"] not in employee_ids:
            raise MigrationError(f"Legacy permission references missing employee: {row['employee_id']}")
        permission = data.get("permission")
        if permission not in {"READ", "ANALYZE", "DRAFT", "REQUEST", "EXECUTE"}:
            raise MigrationError(f"Unsupported legacy permission: {permission!r}")
        conn.execute(
            """
            INSERT INTO permissions_v2 (employee_id, tool_id, permission, requires_approval, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["employee_id"],
                data.get("tool_id", row["tool_id"]),
                permission,
                1 if bool(data.get("requires_approval", False)) else 0,
                data.get("notes"),
                data.get("updated_at") or "",
            ),
        )


def _migrate_memories(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, employee_id, status, priority, data, created_at FROM memories").fetchall()
    employee_ids = {r[0] for r in conn.execute("SELECT id FROM employees_v2")}
    pending_supersedes: list[tuple[str, str]] = []
    valid_ids = {r["id"] for r in rows}

    for row in rows:
        data = _load_json(row["data"], f"memories/{row['id']}")
        if row["employee_id"] not in employee_ids:
            raise MigrationError(f"Legacy memory references missing employee: {row['employee_id']}")
        category = data.get("category", "learned_rule")
        if category not in ALLOWED_MEMORY_CATEGORIES:
            raise MigrationError(f"Unsupported legacy memory category: {category!r}")
        status = data.get("status", row["status"])
        if status not in ALLOWED_MEMORY_STATUS:
            raise MigrationError(f"Unsupported legacy memory status: {status!r}")
        scope = _normalize_scope(data.get("scope"))
        title = str(data.get("title", "Untitled memory"))
        supersedes = data.get("supersedes")
        if supersedes:
            if supersedes not in valid_ids:
                raise MigrationError(f"Memory {row['id']} supersedes missing memory {supersedes}")
            pending_supersedes.append((row["id"], supersedes))

        confidence = float(data.get("confidence_score", 0.5))
        if not 0.0 <= confidence <= 1.0:
            raise MigrationError(f"Invalid confidence_score for memory {row['id']}: {confidence}")
        priority = int(data.get("priority", row["priority"] or 3))
        if not 1 <= priority <= 5:
            raise MigrationError(f"Invalid priority for memory {row['id']}: {priority}")
        version = int(data.get("version", 1))
        if version < 1:
            raise MigrationError(f"Invalid version for memory {row['id']}: {version}")

        conn.execute(
            """
            INSERT INTO memories_v2 (
                id, employee_id, category, scope, applies_to_stages_json, rule_key,
                title, distilled_rule, status, priority, confidence_score, version,
                supersedes, data, created_at, activated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                row["id"], row["employee_id"], category, scope,
                _canonical_json(data.get("applies_to_stages", ["PLAN", "COMPOSE"])),
                _rule_key(category, scope, title),
                title,
                str(data.get("distilled_rule", "")),
                status,
                priority,
                confidence,
                version,
                row["data"],
                row["created_at"],
                data.get("activated_at"),
            ),
        )

    for memory_id, supersedes in pending_supersedes:
        conn.execute(
            "UPDATE memories_v2 SET supersedes = ? WHERE id = ?",
            (supersedes, memory_id),
        )


def _migrate_tasks(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, employee_id, status, data, created_at FROM tasks").fetchall()
    employee_ids = {r[0] for r in conn.execute("SELECT id FROM employees_v2")}
    for row in rows:
        data = _load_json(row["data"], f"tasks/{row['id']}")
        if row["employee_id"] not in employee_ids:
            raise MigrationError(f"Legacy task references missing employee: {row['employee_id']}")
        status = _normalize_task_status(data.get("status", row["status"]))
        conn.execute(
            """
            INSERT INTO tasks_v2 (
                id, employee_id, session_id, task_prompt, status, resume_state,
                pending_action_json, final_output, tokens_used, cost_usd, data, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], row["employee_id"], data.get("session_id"),
                str(data.get("task_prompt", "")), status,
                data.get("resume_state"),
                json.dumps(data.get("pending_action"), ensure_ascii=False) if data.get("pending_action") is not None else None,
                data.get("final_output"), int(data.get("tokens_used", 0) or 0),
                float(data.get("cost_usd", 0.0) or 0.0), row["data"], row["created_at"], data.get("completed_at"),
            ),
        )


def _migrate_audit_log(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, employee_id, task_id, event_type, timestamp, data FROM audit_log"
    ).fetchall()
    for row in rows:
        data = _load_json(row["data"], f"audit_log/{row['id']}")
        conn.execute(
            """
            INSERT INTO audit_log_v2 (
                id, employee_id, task_id, session_id, context_snapshot_id,
                event_type, timestamp, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], row["employee_id"], row["task_id"],
                data.get("session_id"), data.get("context_snapshot_id"),
                row["event_type"], row["timestamp"], row["data"],
            ),
        )


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _pk_set(conn: sqlite3.Connection, table: str) -> set[str]:
    if table in {"permissions", "permissions_v2"}:
        return {
            f"{r[0]}|{r[1]}"
            for r in conn.execute(f"SELECT employee_id, tool_id FROM {table}")
        }
    return {str(r[0]) for r in conn.execute(f"SELECT id FROM {table}")}


def _assert_semantics(conn: sqlite3.Connection) -> None:
    for table in V2_CORE_TABLES:
        expected = _row_count(conn, table)
        actual = _row_count(conn, f"{table}_v2")
        if expected != actual:
            raise MigrationError(f"Row-count mismatch for {table}: {expected} != {actual}")
        if _pk_set(conn, table) != _pk_set(conn, f"{table}_v2"):
            raise MigrationError(f"Primary-key set mismatch for {table}")

    # Field-level semantic checks from the legacy JSON payloads.
    for row in conn.execute("SELECT id, name, department, data FROM employees"):
        data = _load_json(row["data"], f"employees/{row['id']}")
        migrated = conn.execute("SELECT * FROM employees_v2 WHERE id = ?", (row["id"],)).fetchone()
        if migrated["name"] != data.get("name", row["name"]):
            raise MigrationError(f"Employee semantic mismatch: {row['id']} / name")
        if migrated["department"] != data.get("department", row["department"]):
            raise MigrationError(f"Employee semantic mismatch: {row['id']} / department")
        if migrated["role"] != data.get("role", "Autonomous Agent"):
            raise MigrationError(f"Employee semantic mismatch: {row['id']} / role")

    for row in conn.execute("SELECT employee_id, tool_id, data FROM permissions"):
        data = _load_json(row["data"], f"permissions/{row['employee_id']}:{row['tool_id']}")
        migrated = conn.execute(
            "SELECT permission, requires_approval FROM permissions_v2 WHERE employee_id = ? AND tool_id = ?",
            (row["employee_id"], row["tool_id"]),
        ).fetchone()
        if migrated["permission"] != data.get("permission"):
            raise MigrationError(f"Permission semantic mismatch: {row['employee_id']}:{row['tool_id']}")
        expected_approval = 1 if bool(data.get("requires_approval", False)) else 0
        if migrated["requires_approval"] != expected_approval:
            raise MigrationError(f"Permission approval mismatch: {row['employee_id']}:{row['tool_id']}")

    for row in conn.execute("SELECT id, status, priority, data FROM memories"):
        data = _load_json(row["data"], f"memories/{row['id']}")
        migrated = conn.execute("SELECT * FROM memories_v2 WHERE id = ?", (row["id"],)).fetchone()
        if migrated["status"] != data.get("status", row["status"]):
            raise MigrationError(f"Memory status mismatch: {row['id']}")
        if migrated["priority"] != int(data.get("priority", row["priority"] or 3)):
            raise MigrationError(f"Memory priority mismatch: {row['id']}")
        if migrated["distilled_rule"] != str(data.get("distilled_rule", "")):
            raise MigrationError(f"Memory distilled rule mismatch: {row['id']}")

    for row in conn.execute("SELECT id, status, data FROM tasks"):
        data = _load_json(row["data"], f"tasks/{row['id']}")
        migrated = conn.execute("SELECT task_prompt, status, final_output FROM tasks_v2 WHERE id = ?", (row["id"],)).fetchone()
        if migrated["status"] != data.get("status", row["status"]):
            raise MigrationError(f"Task status mismatch: {row['id']}")
        if migrated["task_prompt"] != str(data.get("task_prompt", "")):
            raise MigrationError(f"Task prompt mismatch: {row['id']}")
        if migrated["final_output"] != data.get("final_output"):
            raise MigrationError(f"Task final output mismatch: {row['id']}")

    for row in conn.execute("SELECT id, event_type, timestamp FROM audit_log"):
        migrated = conn.execute(
            "SELECT event_type, timestamp FROM audit_log_v2 WHERE id = ?", (row["id"],)
        ).fetchone()
        if migrated["event_type"] != row["event_type"] or migrated["timestamp"] != row["timestamp"]:
            raise MigrationError(f"Audit semantic mismatch: {row['id']}")


def _execute_sql_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script statement-by-statement without breaking the caller transaction.

    sqlite3.Connection.executescript() implicitly commits before execution, so it is
    deliberately avoided for migration DDL that must remain inside BEGIN IMMEDIATE.
    sqlite3.complete_statement() correctly handles trigger bodies containing semicolons.
    """
    statement_parts: list[str] = []
    for line in script.splitlines(keepends=True):
        statement_parts.append(line)
        candidate = "".join(statement_parts).strip()
        if candidate and sqlite3.complete_statement(candidate):
            conn.execute(candidate)
            statement_parts.clear()
    trailing = "".join(statement_parts).strip()
    if trailing:
        conn.execute(trailing)


def _create_research_schema(conn: sqlite3.Connection) -> None:
    """Create the complete v2 schema on a fresh database."""
    _execute_sql_script(conn, V2_SCHEMA_SQL)


def _create_research_tables_after_core_swap(conn: sqlite3.Connection) -> None:
    """Create research tables/triggers that do not exist after the legacy-table swap."""
    start = V2_SCHEMA_SQL.index("CREATE TABLE research_sessions")
    end = V2_SCHEMA_SQL.index("CREATE TABLE audit_log")
    _execute_sql_script(conn, V2_SCHEMA_SQL[start:end])

    conn.execute("""
        CREATE TRIGGER trg_audit_log_no_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is strictly append-only: UPDATE is forbidden');
        END;
    """)
    conn.execute("""
        CREATE TRIGGER trg_audit_log_no_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is strictly append-only: DELETE is forbidden');
        END;
    """)


def _integrity_check(conn: sqlite3.Connection) -> None:
    fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_issues:
        raise MigrationError(f"Foreign-key violations after migration: {fk_issues[:5]}")
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise MigrationError(f"SQLite integrity_check failed: {result}")


def _current_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_migrations"):
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def _has_any_user_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1
        """
    ).fetchone()
    return row is not None


def _swap_core_tables(conn: sqlite3.Connection) -> None:
    for table in ["employees", "permissions", "memories", "tasks", "audit_log"]:
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_v2 RENAME TO {table}")

    conn.execute("CREATE INDEX idx_memories_emp_status_scope ON memories(employee_id, status, scope, priority ASC, created_at DESC)")
    conn.execute("CREATE INDEX idx_memories_emp_rule_key ON memories(employee_id, rule_key, status)")
    conn.execute("CREATE INDEX idx_audit_task_time ON audit_log(task_id, timestamp DESC)")


def run_migrations(db_path: str | None = None) -> None:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    try:
        version = _current_version(conn)
        if version >= SCHEMA_VERSION:
            return
        had_existing_tables = _has_any_user_tables(conn)
    finally:
        conn.close()

    if had_existing_tables:
        backup_path = Path(f"{path}.v1.bak")
        wal_safe_backup(path, backup_path)
        check = sqlite3.connect(str(backup_path))
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise MigrationError(f"Backup integrity_check failed: {result}")
        finally:
            check.close()

    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )

            if not had_existing_tables:
                _create_research_schema(conn)
            else:
                for table in V2_CORE_TABLES:
                    if not _table_exists(conn, table):
                        raise MigrationError(f"Required legacy table missing: {table}")
                    _create_v2_core_table(conn, table)

                _migrate_employees(conn)
                _migrate_permissions(conn)
                _migrate_memories(conn)
                _migrate_tasks(conn)
                _migrate_audit_log(conn)
                _assert_semantics(conn)
                _swap_core_tables(conn)

                _create_research_tables_after_core_swap(conn)

            _integrity_check(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                (SCHEMA_VERSION,),
            )
            _integrity_check(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    except Exception as exc:
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"Migration failed: {exc}") from exc
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()
