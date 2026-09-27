"""Maya Verifier — invokes DomainVerificationService and persists append-only Evidence rows.

SQLite triggers enforce evidence immutability (BEFORE UPDATE / BEFORE DELETE).
The verifier never overwrites an existing evidence row; it deduplicates via content_hash
and synchronizes mutable candidate `claims` + `claim_evidence` composite foreign keys.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.agents.schemas.evidence import VerificationEvidence, compute_evidence_content_hash
from app.agents.schemas.session import ResearchSession
from app.db.connection import DB_PATH, get_connection, transaction

logger = logging.getLogger(__name__)

MAX_EXCERPT_CHARS = 500

_VALID_CLAIM_FIELDS = {
    "identity",
    "website",
    "platform",
    "installed_apps",
    "paid_app_subscription",
    "d2c_status",
    "revenue",
    "technical_observables",
    "performance_audit",
    "contact",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MayaVerifier:
    """Invokes DomainVerificationService for each unaudited candidate and persists Evidence rows."""

    def __init__(
        self,
        session: ResearchSession,
        db_path: Optional[str] = None,
        verifier_service: Optional[Any] = None,
    ) -> None:
        self.session = session
        self._explicit_db_path = db_path
        self._verifier = verifier_service

    @property
    def _db_path(self) -> str:
        import app.db.connection as _conn_mod
        return self._explicit_db_path or _conn_mod.DB_PATH


    def _get_verifier(self) -> Any:
        if self._verifier is not None:
            return self._verifier
        from app.services.domain_verifier import DomainVerificationService
        return DomainVerificationService(timeout=5)

    def verify_candidate(self, candidate: Dict[str, Any]) -> List[str]:
        """Verify a single candidate and persist append-only evidence + mutable claims."""
        cid = candidate["id"]
        url = candidate.get("initial_url") or candidate.get("canonical_domain", "")
        if not url:
            logger.warning("[Verifier] Candidate %s has no URL; skipping", cid)
            return []

        if (self.session.verification_requests_made or 0) >= self.session.max_verification_requests:
            logger.info("[Verifier] Max verification requests reached (%d)", self.session.max_verification_requests)
            return []

        verifier = self._get_verifier()
        self.session.verification_requests_made = (self.session.verification_requests_made or 0) + 1

        try:
            result = verifier.verify(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Verifier] verify(%s) raised: %s", url, exc)
            self._update_candidate_reachability(cid, reachable=False, http_status=None, storefront_state="dead")
            self._mark_audited(cid)
            return []

        reachable = bool(getattr(result, "reachable", False))
        http_status = getattr(result, "http_status", None)
        page_available = getattr(result, "page_available", None)
        storefront_state = getattr(result, "storefront_state", "unknown") or "unknown"
        final_url = getattr(result, "final_url", None) or url

        self._update_candidate_reachability(
            cid,
            reachable=reachable,
            http_status=http_status,
            page_available=page_available,
            storefront_state=storefront_state,
            final_url=final_url,
        )

        raw_evidence: List[VerificationEvidence] = getattr(result, "evidence", []) or []
        inserted_ids: List[str] = []

        for ve in raw_evidence:
            ev_id = self._persist_evidence(cid, ve)
            if ev_id:
                inserted_ids.append(ev_id)

        self._mark_audited(cid)
        self.session.candidates_verified = (self.session.candidates_verified or 0) + 1

        logger.info(
            "[Verifier][session=%s] candidate=%s url=%s reachable=%s evidence=%d",
            self.session.id,
            cid,
            url,
            reachable,
            len(inserted_ids),
        )
        return inserted_ids

    def verify_batch(self, candidates: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Verify a list of candidates. Returns mapping candidate_id → evidence_ids."""
        results: Dict[str, List[str]] = {}
        for cand in candidates:
            if (self.session.verification_requests_made or 0) >= self.session.max_verification_requests:
                break
            results[cand["id"]] = self.verify_candidate(cand)
        return results

    def _persist_evidence(self, candidate_id: str, ve: VerificationEvidence) -> Optional[str]:
        """Append a VerificationEvidence as an Evidence row and sync mutable Claim."""
        retrieved_at = getattr(ve, "retrieved_at", None) or _utc_now()
        raw_excerpt = (getattr(ve, "raw_excerpt", "") or "")[:MAX_EXCERPT_CHARS]
        supports_field = "installed_apps" if ve.supports_field == "apps" else ve.supports_field

        content_hash = compute_evidence_content_hash(
            candidate_id=candidate_id,
            source_url=ve.source_url,
            source_type=ve.source_type,
            supports_field=supports_field,
            signal_type=ve.signal_type,
            extracted_value=ve.extracted_value,
            raw_excerpt=raw_excerpt,
        )

        try:
            with transaction(self._db_path) as conn:
                existing = conn.execute(
                    "SELECT id FROM evidence WHERE session_id=? AND candidate_id=? AND content_hash=?",
                    (self.session.id, candidate_id, content_hash),
                ).fetchone()
                if existing:
                    ev_id = existing["id"]
                else:
                    ev_id = f"E{uuid.uuid4().hex[:12]}"
                    conn.execute(
                        """
                        INSERT INTO evidence (
                            id, session_id, candidate_id, verifier_version,
                            source_url, source_type, supports_field, signal_type,
                            extracted_value, raw_excerpt, confidence, content_hash, retrieved_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ev_id,
                            self.session.id,
                            candidate_id,
                            getattr(ve, "verifier_version", "v2.0"),
                            ve.source_url,
                            ve.source_type,
                            supports_field,
                            ve.signal_type,
                            ve.extracted_value,
                            raw_excerpt,
                            ve.confidence,
                            content_hash,
                            retrieved_at,
                        ),
                    )

                # Sync mutable claim & composite FK claim_evidence if field is in claims schema
                # and confidence is HIGH or MEDIUM
                if supports_field in _VALID_CLAIM_FIELDS and ve.confidence in ("HIGH", "MEDIUM"):
                    claim_id = f"clm_{candidate_id}_{supports_field}"
                    cur_claim = conn.execute(
                        "SELECT id, value FROM claims WHERE candidate_id=? AND field=?",
                        (candidate_id, supports_field),
                    ).fetchone()
                    new_val = ve.extracted_value
                    if cur_claim and supports_field == "installed_apps" and cur_claim["value"]:
                        prev_apps = [a.strip() for a in cur_claim["value"].split(",") if a.strip() and "UNVERIFIED" not in a]
                        new_apps = [a.strip() for a in new_val.split(",") if a.strip()]
                        merged = list(dict.fromkeys(prev_apps + new_apps))
                        new_val = ", ".join(merged)
                        claim_id = cur_claim["id"]
                    elif cur_claim:
                        claim_id = cur_claim["id"]

                    conn.execute(
                        """
                        INSERT INTO claims (id, session_id, candidate_id, field, value, status, version, updated_at)
                        VALUES (?, ?, ?, ?, ?, 'SUPPORTED', 1, ?)
                        ON CONFLICT(candidate_id, field) DO UPDATE SET
                            value=excluded.value,
                            status='SUPPORTED',
                            version=claims.version+1,
                            updated_at=excluded.updated_at
                        """,
                        (claim_id, self.session.id, candidate_id, supports_field, new_val, retrieved_at),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO claim_evidence (claim_id, evidence_id, session_id, candidate_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (claim_id, ev_id, self.session.id, candidate_id),
                    )
            return ev_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Verifier] persist_evidence failed for candidate=%s: %s", candidate_id, exc)
            return None

    def _update_candidate_reachability(
        self,
        candidate_id: str,
        *,
        reachable: bool,
        http_status: Optional[int],
        page_available: Optional[bool] = None,
        storefront_state: str = "unknown",
        final_url: Optional[str] = None,
    ) -> None:
        try:
            with transaction(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE candidates
                    SET http_reachable=?, http_status=?, page_available=?,
                        storefront_state=?, final_url=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        1 if reachable else 0,
                        http_status,
                        (1 if page_available else 0) if page_available is not None else None,
                        storefront_state,
                        final_url,
                        _utc_now(),
                        candidate_id,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Verifier] update_candidate_reachability(%s) failed: %s", candidate_id, exc)

    def _mark_audited(self, candidate_id: str) -> None:
        try:
            with transaction(self._db_path) as conn:
                conn.execute(
                    "UPDATE candidates SET audited_by_verifier=1, updated_at=? WHERE id=?",
                    (_utc_now(), candidate_id),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Verifier] mark_audited(%s) failed: %s", candidate_id, exc)

    def get_evidence_for_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        """Return all evidence rows for a candidate from SQLite."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, session_id, candidate_id, source_url, source_type,
                       supports_field, signal_type, extracted_value, raw_excerpt, confidence
                FROM evidence WHERE candidate_id=? AND session_id=?
                """,
                (candidate_id, self.session.id),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
