"""Task state machine — Python owns the loop; LLM never decides when to stop.

Wraps ResearchSession.transition_to() with:
- Forward-only hop budget enforcement
- SQL-derived candidate metrics via store.get_session_metrics()
- Structured audit logging on every transition
- Deterministic should_continue_discovery() without LLM input
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.agents.schemas.session import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransitionError,
    ResearchSession,
    SessionStatus,
)
from app.db import store as _store

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStateMachine:
    """Python control-plane wrapper around ResearchSession state transitions.

    The machine is the single source of truth for whether a hop is allowed and
    whether discovery should continue.  The LLM never touches these decisions.
    """

    def __init__(self, session: ResearchSession, task_id: str) -> None:
        self.session = session
        self.task_id = task_id
        self._transition_log: list[dict] = []

    # ------------------------------------------------------------------
    # Public transition API
    # ------------------------------------------------------------------

    def transition(self, next_state: SessionStatus, reason: str = "") -> SessionStatus:
        """Transition the session and persist the new status to SQLite.

        Raises InvalidStateTransitionError on any illegal move.
        """
        previous = self.session.status
        self.session.transition_to(next_state)  # raises on illegal move

        entry = {
            "from": previous,
            "to": next_state,
            "hop": self.session.current_hop,
            "reason": reason,
            "at": _utc_now(),
        }
        self._transition_log.append(entry)

        logger.info(
            "[TaskStateMachine][session=%s] %s → %s (hop=%d) %s",
            self.session.id,
            previous,
            next_state,
            self.session.current_hop,
            f"— {reason}" if reason else "",
        )

        self._persist_session_status()
        return self.session.status

    def resume_from_approval(self, task: object) -> SessionStatus:
        """Resume from waiting_approval using task.resume_state (locked, caller cannot pick destination)."""
        previous = self.session.status
        result = self.session.resume_from_approval(task)

        self._transition_log.append({
            "from": previous,
            "to": result,
            "hop": self.session.current_hop,
            "reason": "founder_approval",
            "at": _utc_now(),
        })

        logger.info(
            "[TaskStateMachine][session=%s] resume_from_approval: %s → %s",
            self.session.id,
            previous,
            result,
        )

        self._persist_session_status()
        return result

    # ------------------------------------------------------------------
    # Deterministic termination check (Python only)
    # ------------------------------------------------------------------

    def should_continue_discovery(self) -> bool:
        """Pull live candidate counts from SQLite and apply deterministic budget checks.

        This is the only function that decides whether the pipeline enters another
        DISCOVER hop.  The LLM is never consulted.
        """
        metrics = _store.get_session_metrics(self.session.id)
        viable = metrics.get("verified", 0) + metrics.get("prospect", 0)

        # Sync live counters into the session (for telemetry only, not for decisions)
        self.session.candidates_found = metrics.get("candidates", 0)
        self.session.candidates_verified = metrics.get("verified", 0)

        result = self.session.should_continue_discovery(viable)

        logger.info(
            "[TaskStateMachine][session=%s] should_continue_discovery=%s "
            "viable=%d target=%d hop=%d/%d",
            self.session.id,
            result,
            viable,
            self.session.target_verified_leads,
            self.session.current_hop,
            self.session.max_hops,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist_session_status(self) -> None:
        """Write current session status and counters back to research_sessions table."""
        try:
            import json
            import app.db.connection as _conn_mod
            from app.db.connection import transaction
            db_status = "failed" if self.session.status == "rejected" else self.session.status
            term_reason = (
                self.session.termination_reason or "Rejected by founder"
                if self.session.status == "rejected"
                else self.session.termination_reason
            )
            with transaction(_conn_mod.DB_PATH) as conn:
                conn.execute(
                    """
                    UPDATE research_sessions
                    SET status=?, current_hop=?, target_verified_leads=?, max_hops=?,
                        search_queries_json=?, termination_reason=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        db_status,
                        self.session.current_hop,
                        self.session.target_verified_leads,
                        self.session.max_hops,
                        json.dumps(self.session.search_queries_used or []),
                        term_reason,
                        _utc_now(),
                        self.session.id,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TaskStateMachine] Failed to persist session status: %s", exc)


    @property
    def current_state(self) -> SessionStatus:
        return self.session.status

    @property
    def transition_log(self) -> list[dict]:
        return list(self._transition_log)
