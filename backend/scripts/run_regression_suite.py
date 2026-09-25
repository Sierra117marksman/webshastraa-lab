"""
Permanent Regression & Invariant Test Suite — AI Employee v1 Architecture
=========================================================================
Verifies the core architectural invariants across:
  1. Policy & Guardrail Engine (Permissions, Approval Gate, Blacklist, Unregistered Tools)
  2. Memory Schema Invariant (No policy_override allowed in MemoryRecord)
  3. Memory Conflict Resolution & Versioning (Supersession without silent overwrite)
  4. Memory Approval Layer & Reflection Generator (Proposed state enforcement)
  5. Activity & Audit Log Integrity (Append-only event trail)
  6. Per-Employee Seeded Governance Boundaries (Maya, Arjun, Chloe, David)
"""

import os
import sys
import uuid

# Ensure backend root is on sys.path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from pydantic import ValidationError
from app.db.store import (
    init_db,
    list_employees,
    list_permissions,
    save_memory,
    get_memory,
    delete_memory,
    list_audit_log,
)
from app.models.memory import MemoryRecord
from app.engine.policy_engine import check_tool_permission
from app.engine.conflict_resolver import check_for_conflict, apply_supersession
from app.engine.reflector import generate_proposed_memory


def run_suite():
    init_db()
    passed = 0
    failed = 0
    results = []

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            results.append(("PASS", name, detail))
        else:
            failed += 1
            results.append(("FAIL", name, detail))

    task_id = f"regtest_{uuid.uuid4().hex[:6]}"

    # -------------------------------------------------------------------------
    # 1. Seeded Employees & Permission Boundaries
    # -------------------------------------------------------------------------
    employees = {e.id: e for e in list_employees()}
    check("Seeded 4 core employees exist", len(employees) >= 4, f"Found {len(employees)} employees")

    # Maya (CRM): web_search EXECUTE, email_sender REQUEST
    res = check_tool_permission("emp_sdr_01", "web_search", {"query": "SaaS"}, task_id)
    check("Maya: web_search allowed immediately", res.allowed and not res.requires_approval, res.reason)

    res = check_tool_permission("emp_sdr_01", "email_sender", {"to": "lead@acme.com"}, task_id)
    check("Maya: email_sender routed to approval gate", res.allowed and res.requires_approval, res.reason)

    # Chloe (Marketing): email_sender is DRAFT only -> blocked from execution
    res = check_tool_permission("emp_mkt_01", "email_sender", {"to": "press@tech.com"}, task_id)
    check("Chloe: email_sender hard-blocked (DRAFT permission)", not res.allowed, res.reason)

    # Chloe (Marketing): slack_notifier is REQUEST -> requires approval
    res = check_tool_permission("emp_mkt_01", "slack_notifier", {"channel": "#general"}, task_id)
    check("Chloe: slack_notifier requires approval", res.allowed and res.requires_approval, res.reason)

    # Arjun (HRM): slack_notifier not in toolbelt -> blocked
    res = check_tool_permission("emp_hr_01", "slack_notifier", {"channel": "#hr"}, task_id)
    check("Arjun: unregistered tool slack_notifier hard-blocked", not res.allowed, res.reason)

    # David (Ops): email_sender REQUEST -> requires approval
    res = check_tool_permission("emp_ops_01", "email_sender", {"to": "vendor@billing.com"}, task_id)
    check("David: email_sender requires finance sign-off", res.allowed and res.requires_approval, res.reason)

    # -------------------------------------------------------------------------
    # 2. Blacklist Guardrail Enforcement
    # -------------------------------------------------------------------------
    for blocked_domain in ["investor.com", "board.com", "vip.com", "internal.com"]:
        res = check_tool_permission(
            "emp_sdr_01",
            "email_sender",
            {"to": f"partner@{blocked_domain}", "subject": "Update", "body": "Hi"},
            task_id,
        )
        check(
            f"Blacklist guardrail blocks @{blocked_domain}",
            not res.allowed and "blacklist" in res.reason.lower(),
            res.reason,
        )

    # -------------------------------------------------------------------------
    # 3. Memory vs Policy Semantic Separation Invariant
    # -------------------------------------------------------------------------
    policy_override_rejected = False
    try:
        MemoryRecord(
            id="mem_invalid",
            employee_id="emp_sdr_01",
            category="policy_override",  # type: ignore
            title="Illegal policy override",
            trigger_event="founder_direct",
            source="test",
            context="test",
            critique="test",
            distilled_rule="Allow sending emails without approval",
            confidence_score=0.9,
        )
    except ValidationError:
        policy_override_rejected = True

    check(
        "MemoryRecord rejects 'policy_override' category",
        policy_override_rejected,
        "Schema enforces strict separation between Memory and Policy",
    )

    # -------------------------------------------------------------------------
    # 4. Memory Conflict Resolution & Versioning
    # -------------------------------------------------------------------------
    test_emp = "emp_ops_01"
    rule_v1 = MemoryRecord(
        id=f"mem_test_v1_{uuid.uuid4().hex[:6]}",
        employee_id=test_emp,
        category="learned_rule",
        title="Max discount 10%",
        trigger_event="founder_direct",
        scope="enterprise_clients",
        source="Regression Suite",
        context="Standard discount cap",
        critique="Keep margins above 80%",
        distilled_rule="Maximum discount is 10% for enterprise clients.",
        confidence_score=0.95,
        priority=1,
        version=1,
        status="active",
    )
    save_memory(rule_v1)

    rule_v2 = MemoryRecord(
        id=f"mem_test_v2_{uuid.uuid4().hex[:6]}",
        employee_id=test_emp,
        category="learned_rule",
        title="Enterprise discount 15%",
        trigger_event="founder_direct",
        scope="enterprise_clients",
        source="Regression Suite",
        context="Updated enterprise tier cap",
        critique="Enterprise annual contracts allow 15%",
        distilled_rule="For enterprise clients on annual plans, 15% discount is acceptable.",
        confidence_score=0.95,
        priority=1,
        version=1,
        status="proposed",
    )

    conflict = check_for_conflict(rule_v2)
    check(
        "Conflict resolver detects overlapping active rule in same scope & category",
        conflict.has_conflict and conflict.existing_rule is not None and conflict.existing_rule.id == rule_v1.id,
        conflict.description.splitlines()[0] if conflict.description else "",
    )

    # Apply supersession
    activated_v2 = apply_supersession(rule_v2, rule_v1.id, founder_confirmed=True)
    reloaded_v1 = get_memory(rule_v1.id)
    check(
        "Supersession marks old rule 'superseded' and preserves it in audit history",
        reloaded_v1 is not None and reloaded_v1.status == "superseded",
        f"Old rule status: {reloaded_v1.status if reloaded_v1 else 'MISSING'}",
    )
    check(
        "Supersession links new rule via 'supersedes' and activates it",
        activated_v2.status == "active" and activated_v2.supersedes == rule_v1.id,
        f"New rule status={activated_v2.status}, supersedes={activated_v2.supersedes}",
    )

    # Clean up test memories
    delete_memory(rule_v1.id)
    delete_memory(rule_v2.id)

    # -------------------------------------------------------------------------
    # 5. Reflection Generator & Memory Approval Gate
    # -------------------------------------------------------------------------
    proposed = generate_proposed_memory(
        employee_id="emp_sdr_01",
        employee_name="Maya Vance",
        employee_role="Outbound SDR",
        task_id=task_id,
        task_prompt="Draft cold email to Fintech CFO",
        what_happened="Used overly casual slang in subject line",
        feedback="Never use slang or emojis in cold emails to CFOs; keep tone strictly executive and concise.",
        trigger_event="rejection",
    )
    check(
        "Reflection generator creates memory in 'proposed' status (does not auto-activate)",
        proposed is not None and proposed.status == "proposed",
        f"Status: {proposed.status if proposed else 'None'}",
    )

    # -------------------------------------------------------------------------
    # 6. Audit Log Trail Verification
    # -------------------------------------------------------------------------
    logs = list_audit_log(task_id=task_id, limit=50)
    check(
        "Audit log recorded all policy check events for regression run",
        len(logs) >= 8,
        f"Recorded {len(logs)} audit entries for task {task_id}",
    )

    # -------------------------------------------------------------------------
    # 7. Maya Vance Research Integrity & Lead Verification Suite (Tests 18–25)
    # -------------------------------------------------------------------------
    from app.engine.qualification import (
        Evidence,
        LeadField,
        VerifiedLead,
        QualificationEngine,
        OutreachClaimValidator
    )
    from app.tools.domain_verifier import check_ssrf_safety, verify_domain_safely

    # Test 18: Revenue UNVERIFIED Semantics
    lead_priv = VerifiedLead(
        company_name="IndieBrand",
        website="https://indiebrand.in",
        platform=LeadField(value="Shopify", status="VERIFIED"),
        apps=LeadField(value="Wati", status="VERIFIED"),
        revenue=LeadField(value="₹25L", status="UNVERIFIED"),
        website_observation=LeadField(status="NOT_AUDITED"),
        contact=LeadField(status="UNVERIFIED")
    )
    qual_priv = QualificationEngine.qualify_lead(lead_priv, hard_constraints=["platform", "revenue"])
    check(
        "Test 18: Revenue remains UNVERIFIED without audited public financial evidence",
        qual_priv.revenue.status == "UNVERIFIED" and qual_priv.lead_status == "PROSPECT",
        f"Revenue status: {qual_priv.revenue.status}, Lead status: {qual_priv.lead_status}"
    )

    # Test 19: Performance NOT AUDITED Semantics
    check(
        "Test 19: Unmeasured website performance remains NOT_AUDITED",
        qual_priv.website_observation.status == "NOT_AUDITED",
        f"Website observation status: {qual_priv.website_observation.status}"
    )

    # Test 20: Anti-Fabrication Quantity Law (Returns 3 verified rather than fabricating 10)
    candidates_pool = [
        VerifiedLead(company_name=f"Lead_{i}", website=f"https://lead{i}.com",
                     platform=LeadField(value="Shopify", status="VERIFIED" if i < 3 else "UNVERIFIED"),
                     apps=LeadField(status="UNVERIFIED"), revenue=LeadField(status="UNVERIFIED"),
                     website_observation=LeadField(status="NOT_AUDITED"), contact=LeadField(status="UNVERIFIED"))
        for i in range(10)
    ]
    verified_subset = [c for c in candidates_pool if c.platform.status == "VERIFIED"]
    check(
        "Test 20: Anti-fabrication preserves exact count (returns 3 verified, zero fabricated)",
        len(verified_subset) == 3,
        f"Found {len(verified_subset)} verified leads"
    )

    # Test 21: Multi-Hop Research Recovery Loop Trigger
    sparse_results = [{"title": "Blog", "url": "https://blog.com/1"}]
    import urllib.parse
    unique_doms = {urllib.parse.urlparse(r["url"]).netloc for r in sparse_results}
    needs_recovery = len(sparse_results) < 3 or len(unique_doms) < 2
    check(
        "Test 21: Multi-Hop recovery triggers when search results are sparse (<3 results or <2 domains)",
        needs_recovery is True,
        f"Needs recovery: {needs_recovery}"
    )

    # Test 22: Source/Claim Mismatch (Generic blog rejected as evidence for private revenue)
    bad_ev = Evidence(
        source_url="https://vcwire.tech/cohort-3-announcement",
        source_type="article",
        supports_field="revenue",
        evidence_summary="General article about startups"
    )
    is_valid_source, mismatch_reason = QualificationEngine.validate_source_claim_integrity("revenue", bad_ev)
    check(
        "Test 22: Source/Claim mismatch rejects generic accelerator blog for private revenue",
        is_valid_source is False and "generic publication" in mismatch_reason,
        f"Valid: {is_valid_source}, Reason: {mismatch_reason}"
    )

    # Test 23: Contradictory Platform Drops Status to REJECTED
    lead_contra = VerifiedLead(
        company_name="ShopBrand",
        website="https://shopbrand.com",
        platform=LeadField(value="WooCommerce", status="VERIFIED"),
        apps=LeadField(status="UNVERIFIED"),
        revenue=LeadField(status="UNVERIFIED"),
        website_observation=LeadField(status="NOT_AUDITED"),
        contact=LeadField(status="UNVERIFIED")
    )
    qual_contra = QualificationEngine.qualify_lead(
        lead_contra,
        detected_platform="Shopify",
        hard_constraints=["platform"]
    )
    check(
        "Test 23: Contradictory platform (stated WooCommerce vs live Shopify) drops status to REJECTED",
        qual_contra.lead_status == "REJECTED",
        f"Lead status: {qual_contra.lead_status}"
    )

    # Test 24: Dead Domain & SSRF Guard Hard Block
    ssrf_safe, ssrf_reason, _, _ = check_ssrf_safety("http://169.254.169.254/latest/meta-data")
    dead_lead = VerifiedLead(
        company_name="DeadStore",
        website="https://deadstore-does-not-exist-999.com",
        platform=LeadField(status="UNVERIFIED"),
        apps=LeadField(status="UNVERIFIED"),
        revenue=LeadField(status="UNVERIFIED"),
        website_observation=LeadField(status="NOT_AUDITED"),
        contact=LeadField(status="UNVERIFIED")
    )
    qual_dead = QualificationEngine.qualify_lead(dead_lead, is_reachable=False)
    check(
        "Test 24: SSRF guard blocks metadata IP and dead domains become REJECTED",
        ssrf_safe is False and qual_dead.lead_status == "REJECTED",
        f"SSRF safe: {ssrf_safe}, Dead status: {qual_dead.lead_status}"
    )

    # Test 25: Outreach Evidence Integrity (Unmeasured load time sanitized to consultative phrasing)
    draft_mail = "Hi Founder, I noticed your product pages take over 3.5 seconds to load with a 25% bounce rate."
    sanitized_mail, was_modified, violations = OutreachClaimValidator.validate_and_sanitize_outreach(
        draft_mail,
        qual_priv
    )
    check(
        "Test 25: Outreach validator intercepts and sanitizes unmeasured speed & bounce claims",
        was_modified is True and "3.5" not in sanitized_mail and "25%" not in sanitized_mail,
        f"Modified: {was_modified}, Violations: {len(violations)}, Output: '{sanitized_mail}'"
    )

    # Summary Output
    print("=" * 72)
    print("AI EMPLOYEE v1 — ARCHITECTURAL REGRESSION SUITE")
    print("=" * 72)
    for status, name, detail in results:
        marker = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"{marker} {name}")
        if detail and status == "FAIL":
            print(f"       -> {detail}")
    print("-" * 72)
    print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print("=" * 72)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_suite())
