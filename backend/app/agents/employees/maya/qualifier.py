from typing import List
from app.agents.schemas.candidate import Candidate, CandidateLedger
from app.agents.schemas.evidence import EvidenceStore
from app.agents.schemas.session import ResearchSession


class MayaQualifier:
    """
    Deterministic Qualification Engine separating Research from Qualification.
    Evaluates field-specific Claims and EvidenceStore bindings against
    ResearchSession.hard_constraints.
    """

    @classmethod
    def qualify_ledger(
        cls,
        ledger: CandidateLedger,
        session: ResearchSession,
        evidence_store: EvidenceStore
    ) -> None:
        for cand in ledger.candidates.values():
            if not cand.audited_by_verifier:
                continue
            cls.qualify_candidate(cand, session, evidence_store)

    @classmethod
    def qualify_candidate(
        cls,
        cand: Candidate,
        session: ResearchSession,
        evidence_store: EvidenceStore
    ) -> Candidate:
        reasons: List[str] = []
        failed: List[str] = list(cand.failed_checks)

        # 0. Verify all SUPPORTED claims actually map to existing Evidence objects in EvidenceStore
        for field_name, claim in cand.get_all_claims().items():
            if claim.status == "SUPPORTED":
                valid_ids = [eid for eid in claim.evidence_ids if evidence_store.get(eid) is not None]
                claim.evidence_ids = valid_ids
                if not valid_ids:
                    claim.status = "UNVERIFIED"
                    claim.notes = "Downgraded: referenced evidence ID not found in EvidenceStore."

        # 1. Website reachability / validity check
        if cand.website.status == "CONTRADICTED":
            cand.qualification_status = "REJECTED"
            failed.append("Domain unreachable or invalid.")
            cand.failed_checks = failed
            cand.qualification_reasons = ["Rejected: Domain unreachable or failed SSRF/HTTP check."]
            return cand

        # 2. Platform constraint check
        target_platform = session.hard_constraints.get("platform")
        if target_platform:
            if cand.platform.status == "SUPPORTED" and cand.platform.value:
                if cand.platform.value.lower() != target_platform.lower():
                    cand.platform.status = "CONTRADICTED"
                    cand.qualification_status = "REJECTED"
                    msg = f"Platform contradiction: required {target_platform}, detected {cand.platform.value}."
                    failed.append(msg)
                    cand.failed_checks = failed
                    cand.qualification_reasons = [msg]
                    return cand
                else:
                    reasons.append(f"Platform={cand.platform.value} [Evidence: {', '.join(cand.platform.evidence_ids)}]")
            else:
                # Neither live HTML nor directory proved the required platform
                cand.qualification_status = "REJECTED"
                msg = f"Unverified platform: could not confirm {target_platform} footprint on {cand.canonical_domain}."
                failed.append(msg)
                cand.failed_checks = failed
                cand.qualification_reasons = [msg]
                return cand

        # 3. Apps constraint check
        unverified_constraints: List[str] = []
        if session.hard_constraints.get("apps"):
            if cand.apps.status == "SUPPORTED" and cand.apps.value:
                reasons.append(f"Apps={cand.apps.value} [Evidence: {', '.join(cand.apps.evidence_ids)}]")
            else:
                unverified_constraints.append("apps (no third-party app script signature detected in HTML)")

        # 4. Private Revenue constraint check (Crucial: Unknown remains UNVERIFIED -> PROSPECT)
        if session.hard_constraints.get("revenue_requested"):
            if cand.revenue.status == "SUPPORTED" and cand.revenue.evidence_ids:
                reasons.append(f"Revenue={cand.revenue.value} [Evidence: {', '.join(cand.revenue.evidence_ids)}]")
            else:
                unverified_constraints.append("revenue (private D2C entity — turnover UNVERIFIED)")

        # 5. Final Tri-State Decision
        if not unverified_constraints:
            cand.qualification_status = "VERIFIED"
            cand.confidence = 0.95
            cand.qualification_reasons = reasons + ["All hard constraints verified with primary evidence."]
        else:
            cand.qualification_status = "PROSPECT"
            cand.confidence = 0.75
            cand.qualification_reasons = reasons + [
                f"Qualified as PROSPECT — unverified fields: {'; '.join(unverified_constraints)}"
            ]

        cand.failed_checks = failed
        return cand
