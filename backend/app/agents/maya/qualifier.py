"""Maya Qualifier — evaluates Claims + Evidence → idempotent QualificationDecision.

Key invariants from Rev 3:
- QualificationDecision is immutable and append-only (SQLite triggers enforce this)
- decision_hash uniqueness prevents duplicate decisions for the same (session, candidate, hop)
- INSERT OR IGNORE on decision_hash → idempotent by design
- trg_sync_candidate_on_decision_insert trigger automatically updates candidates.qualification_status
- LOW_PUBLIC_OBSERVABILITY fields that are UNVERIFIED → PROSPECT (never REJECTED)
- LOW confidence text-only mentions never satisfy platform/app requirements
- Conflicting platform evidence (e.g. Shopify + WooCommerce) is CONTRADICTED → REJECTED
- HTTP 401/403/429 or non-active storefront_state is never classified as VERIFIED
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.agents.schemas.claim import (
    ClaimSnapshotItem,
    QualificationDecision,
    QualificationResult,
    RequirementEvaluation,
    RequirementEvalStatus,
    compute_decision_hash,
)
from app.agents.schemas.requirement import LOW_OBSERVABILITY_FIELDS, Requirement
from app.agents.schemas.session import ResearchSession
import app.db.connection as _conn_mod
from app.db.connection import get_connection, transaction

logger = logging.getLogger(__name__)

_SINGLE_VALUED_FIELDS = {"platform", "storefront_state"}


def _matches_expected(req: Requirement, extracted_values: List[str]) -> Tuple[bool, bool]:
    """Compare extracted evidence values against req.operator and req.expected.

    Returns `(matched, contradicted)`.
    If a single-valued field (like `platform`) has conflicting distinct values
    (e.g., both 'Shopify' and 'WooCommerce'), returns `(False, True)` (CONTRADICTED).
    """
    non_empty = [v.strip() for v in extracted_values if v and v.strip()]
    if not non_empty:
        return False, False

    distinct_lower = {v.lower() for v in non_empty}
    if req.field in _SINGLE_VALUED_FIELDS and len(distinct_lower) > 1:
        # Platform contradiction: multiple distinct platforms detected in HIGH/MEDIUM evidence
        return False, True

    op = req.operator
    exp = req.expected

    if op == "exists" or exp is True or exp == "" or exp is None:
        return True, False

    if op == "equals":
        target = str(exp).strip().lower()
        has_match = any(val.lower() == target or target in val.lower() for val in non_empty)
        has_mismatch = any(val.lower() != target and target not in val.lower() for val in non_empty)
        if has_mismatch and req.field in _SINGLE_VALUED_FIELDS:
            return False, True
        if has_match:
            return True, False
        return False, True

    if op in ("in", "contains_any"):
        if isinstance(exp, (list, tuple, set)):
            targets = [str(x).strip().lower() for x in exp if str(x).strip()]
        else:
            targets = [s.strip().lower() for s in str(exp).split(",") if s.strip()]
        if not targets:
            return True, False
        for val in non_empty:
            val_low = val.lower()
            if any(t in val_low for t in targets):
                return True, False
        return False, False

    return True, False


def _eval_requirement(
    req: Requirement,
    evidence_rows: List[Dict[str, Any]],
) -> Tuple[RequirementEvalStatus, List[str], str]:
    """Evaluate a single Requirement against a list of evidence dicts.

    Only HIGH or MEDIUM confidence evidence from allowed_source_types can satisfy a requirement.
    Returns (status, evidence_ids, reason).
    """
    field = req.field
    field_aliases = {field}
    if field == "installed_apps":
        field_aliases.add("apps")

    allowed_sources = set(req.allowed_source_types or [])
    relevant = [
        e for e in evidence_rows
        if e.get("supports_field") in field_aliases
        and e.get("confidence") in ("HIGH", "MEDIUM")
        and (not allowed_sources or e.get("source_type") in allowed_sources)
    ]

    if not relevant:
        if field == "performance_audit":
            return "NOT_AUDITED", [], f"No speed/performance audit evidence for '{field}'"
        if field in LOW_OBSERVABILITY_FIELDS or req.observability_class == "LOW_PUBLIC_OBSERVABILITY":
            return "UNVERIFIED", [], f"No authoritative public filing for '{field}' (LOW_PUBLIC_OBSERVABILITY)"
        if req.on_unknown == "PROSPECT":
            return "UNVERIFIED", [], f"No structural evidence for '{field}' (on_unknown=PROSPECT)"
        return "UNVERIFIED", [], f"No structural evidence for '{field}'"

    supporting_ids = [e["id"] for e in relevant]
    extracted_vals = [str(e.get("extracted_value") or "") for e in relevant]
    matched, contradicted = _matches_expected(req, extracted_vals)

    if matched:
        return (
            "SATISFIED",
            supporting_ids,
            f"Satisfied '{field}' via {len(relevant)} evidence record(s): {', '.join(extracted_vals[:3])}",
        )
    if contradicted:
        return (
            "CONTRADICTED",
            supporting_ids,
            f"Contradicted '{field}': expected {req.expected!r}, observed {extracted_vals!r}",
        )
    return (
        "UNVERIFIED",
        supporting_ids,
        f"Evidence for '{field}' did not match expected {req.expected!r}",
    )


def _derive_qualification_result(
    requirements: List[Requirement],
    req_results: Dict[str, RequirementEvaluation],
    candidate_row: Optional[Dict[str, Any]] = None,
    evidence_rows: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[QualificationResult, List[str]]:
    """Derive VERIFIED / PROSPECT / REJECTED from requirement evaluations and reachability."""
    notes: List[str] = []
    storefront_degraded = False

    if candidate_row is not None:
        http_reachable = candidate_row.get("http_reachable")
        http_status = candidate_row.get("http_status")
        page_available = candidate_row.get("page_available")
        sf_state = candidate_row.get("storefront_state") or "unknown"
        audited = bool(candidate_row.get("audited_by_verifier"))

        has_dir_evidence = any(
            e.get("source_type") == "storeleads_directory" and e.get("confidence") in ("HIGH", "MEDIUM")
            for e in (evidence_rows or [])
        )
        if http_reachable == 0 and not has_dir_evidence:
            return "REJECTED", ["Domain unreachable and no directory evidence available -> REJECTED"]
        if sf_state in ("dead", "password_locked", "maintenance") and not has_dir_evidence:
            return "REJECTED", [f"Storefront state is '{sf_state}' -> REJECTED"]

        # HTTP 401/403/429 or non-active storefront when audited cannot be called a healthy VERIFIED storefront
        if http_status in (401, 403, 429) or (audited and (sf_state != "active" or not bool(page_available))):
            storefront_degraded = True
            notes.append(
                f"Live HTTP returned status={http_status}, storefront_state='{sf_state}' (not a confirmed active storefront)"
            )


    any_contradicted = False
    all_hard_satisfied = True
    any_unverified = False

    for req in requirements:
        eval_entry = req_results.get(req.id)
        if eval_entry is None:
            continue
        if eval_entry.priority == "HARD":
            if eval_entry.status == "CONTRADICTED":
                any_contradicted = True
                notes.append(f"HARD requirement '{req.field}' CONTRADICTED: {eval_entry.reason}")
            elif eval_entry.status in ("UNVERIFIED", "NOT_AUDITED"):
                all_hard_satisfied = False
                any_unverified = True
                if (
                    req.on_unknown == "REJECT"
                    and req.field not in LOW_OBSERVABILITY_FIELDS
                    and req.observability_class != "LOW_PUBLIC_OBSERVABILITY"
                ):
                    notes.append(f"HARD requirement '{req.field}' UNVERIFIED with on_unknown=REJECT -> REJECTED")
                    return "REJECTED", notes
                notes.append(f"HARD requirement '{req.field}' {eval_entry.status} -> PROSPECT")
            elif eval_entry.status == "SATISFIED":
                notes.append(f"HARD requirement '{req.field}' SATISFIED")

    if any_contradicted:
        return "REJECTED", notes

    if storefront_degraded:
        # If the storefront returned 403/429 and has no satisfied requirements at all, reject; otherwise cap at PROSPECT
        any_satisfied = any(ev.status == "SATISFIED" for ev in req_results.values())
        if not any_satisfied:
            return "REJECTED", notes + ["Rejected: HTTP 401/403/429 with zero verified signals"]
        return "PROSPECT", notes + ["Capped at PROSPECT because live storefront was not confirmed active (HTTP 403/429/degraded)"]

    if all_hard_satisfied and not any_unverified:
        return "VERIFIED", notes

    return "PROSPECT", notes


class MayaQualifier:
    """Evaluates evidence for each candidate and produces idempotent QualificationDecision rows."""

    def __init__(
        self,
        session: ResearchSession,
        requirements: List[Requirement],
        db_path: Optional[str] = None,
    ) -> None:
        self.session = session
        self.requirements = requirements
        self._db_path = db_path

    @property
    def db_path(self) -> str:
        return self._db_path or _conn_mod.DB_PATH

    def qualify_candidate(self, candidate_id: str) -> Optional[QualificationDecision]:
        """Qualify a single candidate and persist an idempotent QualificationDecision."""
        candidate_row = self._get_candidate(candidate_id)
        evidence_rows = self._get_evidence(candidate_id)

        req_results: Dict[str, RequirementEvaluation] = {}
        all_evidence_ids: List[str] = []

        for req in self.requirements:
            status, ev_ids, reason = _eval_requirement(req, evidence_rows)
            req_results[req.id] = RequirementEvaluation(
                requirement_id=req.id,
                field=req.field,
                priority=req.priority,
                status=status,
                evidence_ids=ev_ids,
                reason=reason,
            )
            all_evidence_ids.extend(ev_ids)

        result, notes = _derive_qualification_result(
            self.requirements,
            req_results,
            candidate_row=candidate_row,
            evidence_rows=evidence_rows,
        )

        claims_snapshot, supporting_claim_ids = self._build_claims_snapshot(candidate_id, evidence_rows)
        unique_ev_ids = sorted(set(all_evidence_ids))
        hop = max(1, self.session.current_hop or 1)

        decision_hash = compute_decision_hash(
            session_id=self.session.id,
            candidate_id=candidate_id,
            hop=hop,
            result=result,
            requirement_results=req_results,
            claims_snapshot=claims_snapshot,
            supporting_evidence_ids=unique_ev_ids,
        )

        existing_id = self._find_existing_decision(decision_hash)
        if existing_id:
            logger.info(
                "[Qualifier][session=%s] candidate=%s decision_hash=%s already exists (%s); skipping",
                self.session.id,
                candidate_id,
                decision_hash[:12],
                existing_id,
            )
            return self._load_decision(existing_id)

        decision = QualificationDecision(
            session_id=self.session.id,
            candidate_id=candidate_id,
            hop=hop,
            result=result,
            decision_hash=decision_hash,
            claims_snapshot=claims_snapshot,
            requirement_results=req_results,
            supporting_claim_ids=supporting_claim_ids,
            supporting_evidence_ids=unique_ev_ids,
            notes=notes,
        )
        self._persist_decision(decision)

        logger.info(
            "[Qualifier][session=%s] candidate=%s hop=%d result=%s",
            self.session.id,
            candidate_id,
            hop,
            result,
        )
        return decision

    def qualify_batch(self, candidate_ids: List[str]) -> Dict[str, Optional[QualificationDecision]]:
        """Qualify a list of candidates. Returns mapping candidate_id → decision."""
        return {cid: self.qualify_candidate(cid) for cid in candidate_ids}

    def _get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, session_id, company_name, canonical_domain,
                       http_reachable, http_status, page_available, storefront_state, audited_by_verifier
                FROM candidates WHERE id=? AND session_id=?
                """,
                (candidate_id, self.session.id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _get_evidence(self, candidate_id: str) -> List[Dict[str, Any]]:
        conn = get_connection(self.db_path)
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

    def _build_claims_snapshot(
        self,
        candidate_id: str,
        evidence_rows: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, ClaimSnapshotItem], List[str]]:
        """Build claims snapshot from SQLite `claims` + `evidence` rows for this candidate."""
        snapshot: Dict[str, ClaimSnapshotItem] = {}
        supporting_claim_ids: List[str] = []

        conn = get_connection(self.db_path)
        try:
            claim_rows = conn.execute(
                """
                SELECT id, field, value, status, version
                FROM claims WHERE candidate_id=? AND session_id=?
                """,
                (candidate_id, self.session.id),
            ).fetchall()
            for crow in claim_rows:
                cid_str = crow["id"]
                ev_links = conn.execute(
                    "SELECT evidence_id FROM claim_evidence WHERE claim_id=? AND candidate_id=? AND session_id=?",
                    (cid_str, candidate_id, self.session.id),
                ).fetchall()
                ev_ids = [r["evidence_id"] for r in ev_links]
                snapshot[crow["field"]] = ClaimSnapshotItem(
                    claim_id=cid_str,
                    field=crow["field"],
                    value=crow["value"],
                    status=crow["status"],
                    version=crow["version"],
                    evidence_ids=ev_ids,
                )
                if crow["status"] == "SUPPORTED" and ev_ids:
                    supporting_claim_ids.append(cid_str)
        finally:
            conn.close()

        field_to_ev: Dict[str, List[Dict[str, Any]]] = {}
        for ev in evidence_rows:
            if ev.get("confidence") in ("HIGH", "MEDIUM"):
                field = ev.get("supports_field", "unknown")
                field_to_ev.setdefault(field, []).append(ev)

        for field, evs in field_to_ev.items():
            if field not in snapshot:
                snap_id = f"snap_{candidate_id}_{field}"
                ev_ids = [e["id"] for e in evs]
                snapshot[field] = ClaimSnapshotItem(
                    claim_id=snap_id,
                    field=field,
                    value=evs[0].get("extracted_value"),
                    status="SUPPORTED" if ev_ids else "UNVERIFIED",
                    version=1,
                    evidence_ids=ev_ids,
                )
                supporting_claim_ids.append(snap_id)

        return snapshot, sorted(set(supporting_claim_ids))

    def _find_existing_decision(self, decision_hash: str) -> Optional[str]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT id FROM qualification_decisions WHERE decision_hash=?",
                (decision_hash,),
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    def _load_decision(self, decision_id: str) -> Optional[QualificationDecision]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT id, session_id, candidate_id, hop, result, decision_hash,
                       engine_version, notes_json, decided_at
                FROM qualification_decisions WHERE id=?
                """,
                (decision_id,),
            ).fetchone()
            if not row:
                return None
            return QualificationDecision(
                id=row["id"],
                session_id=row["session_id"],
                candidate_id=row["candidate_id"],
                hop=row["hop"],
                result=row["result"],
                decision_hash=row["decision_hash"],
                notes=json.loads(row["notes_json"] or "[]"),
            )
        finally:
            conn.close()

    def _persist_decision(self, decision: QualificationDecision) -> None:
        """INSERT OR IGNORE using decision_hash to enforce idempotency."""
        try:
            with transaction(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO qualification_decisions (
                        id, session_id, candidate_id, hop, result, decision_hash,
                        claims_snapshot_json, requirement_results_json,
                        supporting_claim_ids_json, supporting_evidence_ids_json,
                        engine_version, notes_json, decided_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision.id,
                        decision.session_id,
                        decision.candidate_id,
                        decision.hop,
                        decision.result,
                        decision.decision_hash,
                        decision.claims_snapshot_json,
                        decision.requirement_results_json,
                        decision.supporting_claim_ids_json,
                        decision.supporting_evidence_ids_json,
                        decision.engine_version,
                        decision.notes_json,
                        decision.decided_at,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("[Qualifier] Failed to persist QualificationDecision: %s", exc)
            raise
