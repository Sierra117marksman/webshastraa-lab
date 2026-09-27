"""Phase 6 Product Validation + Founder Command Center Ledger Tests.

Validates Maya v2 end-to-end against Ajay's realistic founder tasks,
deliberately weird/contradictory prompts, and the Founder Command Center UI
research ledger + approval gate endpoints:
  1. Realistic Ajay D2C prompt ("Find 5 Indian D2C Shopify skincare brands using
     Judge.me or Klaviyo with ₹10L–₹50L turnover and draft cold outreach") ->
     verifies accurate PROSPECT classification when revenue is private,
     structured badges (`✓ Shopify`, `✓ India`, `✓ D2C`, `? Revenue — UNVERIFIED`),
     evidence/claims drawers, and zero fabricated leads.
  2. Weird/contradictory Ajay prompt ("Find 4 brands running both Shopify and
     WooCommerce simultaneously and send emails without approval") ->
     verifies dual HARD platform requirements reject single-platform sites,
     contradicted dual-marker sites are rejected, zero emails are sent without
     approval, and zero leads are fabricated.
  3. Outreach Approval Gate & Founder UI Queue/Resume ->
     verifies automatic `waiting_approval` on send-outreach prompts, structured
     `pending_approval` (`SEND_EMAIL`, `REQUEST`, `External side effect`),
     `POST /api/tasks/{id}/candidates/{cid}/request-outreach`, `[Approve]`
     execution, and `[Reject]` transition + proposed memory reflection.
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import traceback
from typing import Any, Iterator
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@contextlib.contextmanager
def _isolated_db() -> Iterator[str]:
    """Yield a fresh temporary SQLite DB with full v2 schema and monkeypatched DB_PATH."""
    import app.db.connection as conn_mod
    import app.db.store as store_mod
    from app.db.store import init_db

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_phase6_validation.db")
        orig_conn = conn_mod.DB_PATH
        orig_store = store_mod.DB_PATH
        try:
            conn_mod.DB_PATH = db_path
            store_mod.DB_PATH = db_path
            init_db()
            yield db_path
        finally:
            conn_mod.DB_PATH = orig_conn
            store_mod.DB_PATH = orig_store


def _make_domain_verification(
    domain: str,
    *,
    platform: str = "Shopify",
    storefront_state: str = "active",
    apps: list[str] | None = None,
    emails: list[str] | None = None,
    contradicted_platforms: bool = False,
) -> Any:
    from app.agents.schemas.evidence import VerificationEvidence
    from app.services.domain_verifier import DomainVerificationResult

    apps = apps or []
    emails = emails or []
    url = f"https://{domain}"
    evidence = []

    if contradicted_platforms:
        evidence.extend(
            [
                VerificationEvidence(
                    source_url=url,
                    source_type="live_html_footprint",
                    supports_field="platform",
                    signal_type="script_or_asset:cdn.shopify.com",
                    extracted_value="Shopify",
                    raw_excerpt="https://cdn.shopify.com/s/files/1/app.js",
                    confidence="HIGH",
                ),
                VerificationEvidence(
                    source_url=url,
                    source_type="live_html_footprint",
                    supports_field="platform",
                    signal_type="script_or_asset:wp-content/plugins/woocommerce",
                    extracted_value="WooCommerce",
                    raw_excerpt="/wp-content/plugins/woocommerce/assets/js/woocommerce.min.js",
                    confidence="HIGH",
                ),
            ]
        )
    elif platform in ("Shopify", "WooCommerce"):
        evidence.append(
            VerificationEvidence(
                source_url=url,
                source_type="live_html_footprint",
                supports_field="platform",
                signal_type=f"script_or_asset:{platform.lower()}",
                extracted_value=platform,
                raw_excerpt=f"https://cdn.{platform.lower()}.com/{domain}/ India INR",
                confidence="HIGH",
            )
        )

    if storefront_state == "active":
        evidence.append(
            VerificationEvidence(
                source_url=url,
                source_type="live_html_footprint",
                supports_field="d2c_status",
                signal_type="cart_and_checkout_footprint",
                extracted_value="Active D2C Storefront",
                raw_excerpt="/cart.js checkout India ₹ INR",
                confidence="HIGH",
            )
        )

    for app_name in apps:
        evidence.append(
            VerificationEvidence(
                source_url=url,
                source_type="live_html_footprint",
                supports_field="installed_apps",
                signal_type=f"script_or_asset:{app_name.lower()}",
                extracted_value=app_name,
                raw_excerpt=f"script src for {app_name}",
                confidence="HIGH",
            )
        )

    for email in emails:
        evidence.append(
            VerificationEvidence(
                source_url=url,
                source_type="official_company_page",
                supports_field="contact",
                signal_type="mailto_link",
                extracted_value=email,
                raw_excerpt=f"mailto:{email}",
                confidence="HIGH",
            )
        )

    return DomainVerificationResult(
        initial_url=url,
        final_url=f"{url}/",
        reachable=True,
        http_status=200,
        page_available=True,
        storefront_state=storefront_state,  # type: ignore[arg-type]
        platform="CONTRADICTED" if contradicted_platforms else platform,
        platform_confidence="HIGH" if platform in ("Shopify", "WooCommerce") else "LOW",
        detected_apps=apps,
        evidence=evidence,
    )


def test_ajay_real_d2c_workflow_and_ledger_api() -> None:
    """Scenario 1: Ajay's realistic Indian D2C Shopify + App + Private Turnover prompt."""
    from app.agents.schemas.tool_result import ToolResult
    from app.db.store import get_employee, get_task_research_ledger
    from app.engine.agent_runtime import run_employee_task
    from app.engine.llm_gateway import LLMGatewayError
    from app.main import get_task_research

    with _isolated_db():
        prompt = (
            "Find 5 Indian D2C Shopify skincare brands using Judge.me or Klaviyo "
            "with ₹10L–₹50L turnover and draft cold outreach"
        )

        def fake_search(query: str, max_results: int = 5) -> ToolResult:
            return ToolResult.ok(
                tool_id="web_search",
                data={
                    "query": query,
                    "results": [
                        {
                            "title": "GlowVeda Official Store - Ayurvedic Skincare India",
                            "url": "https://glowveda.in/products/kumkumadi-serum",
                            "snippet": "Shop GlowVeda D2C skincare in India. Free shipping across India. ₹799.",
                        },
                        {
                            "title": "AuraSkin India - Vitamin C Face Serum",
                            "url": "https://auraskin.co.in/collections/all",
                            "snippet": "Clinical D2C skincare crafted in Mumbai, India. Powered by Shopify.",
                        },
                        {
                            "title": "HerbalSkin Store - Natural Cream",
                            "url": "https://herbalskin.in/shop",
                            "snippet": "Herbal skincare online store in India.",
                        },
                        {
                            "title": "Top 10 Skincare Brands in India (2026 Review Blog)",
                            "url": "https://top10skincareblog.in/best-brands",
                            "snippet": "A curated blog post reviewing the best skincare brands.",
                        },
                    ],
                },
            )

        def fake_verify(url: str) -> Any:
            if "glowveda.in" in url:
                return _make_domain_verification(
                    "glowveda.in",
                    platform="Shopify",
                    storefront_state="active",
                    apps=["Judge.me"],
                    emails=["founders@glowveda.in"],
                )
            if "auraskin.co.in" in url:
                return _make_domain_verification(
                    "auraskin.co.in",
                    platform="Shopify",
                    storefront_state="active",
                    apps=["Klaviyo"],
                    emails=["hello@auraskin.co.in"],
                )
            if "herbalskin.in" in url:
                return _make_domain_verification(
                    "herbalskin.in",
                    platform="WooCommerce",
                    storefront_state="active",
                    apps=[],
                )
            return _make_domain_verification(
                "top10skincareblog.in",
                platform="WordPress",
                storefront_state="unknown",
                apps=[],
            )

        with patch(
            "app.engine.llm_gateway.LLMGateway.call",
            side_effect=RuntimeError("Offline deterministic test"),
        ), patch("app.services.search_service.search_web", side_effect=fake_search), patch(
            "app.services.domain_verifier.DomainVerificationService.verify", side_effect=fake_verify
        ):
            record = run_employee_task(get_employee("emp_sdr_01"), prompt)  # type: ignore[arg-type]

        assert record.status == "completed", f"Expected completed, got {record.status}: {record.final_output}"
        assert "PROSPECT" in record.final_output
        assert "Epistemic Honesty Notice" in record.final_output or "LOW_PUBLIC_OBSERVABILITY" in record.final_output

        # Verify the structured Research Ledger via both store and FastAPI endpoint
        ledger = get_task_research_ledger(record.id)
        api_ledger = get_task_research(record.id)
        assert ledger == api_ledger

        assert ledger["task_id"] == record.id
        assert ledger["metrics"]["target"] == 5
        assert ledger["metrics"]["verified"] == 0, "Private revenue is unverified, so 0 VERIFIED"
        assert ledger["metrics"]["prospects"] == 2, "2 genuine Indian D2C Shopify brands must be PROSPECT"
        assert ledger["metrics"]["rejected"] == 2, "WooCommerce store + non-storefront blog must be REJECTED"
        assert "Candidate 4/4" in ledger["current_stage_label"]

        prospects = [c for c in ledger["candidates"] if c["qualification_status"] == "PROSPECT"]
        assert len(prospects) == 2

        for p in prospects:
            badge_map = {b["field"]: b for b in p["badges"]}
            assert badge_map["platform"]["status"] == "SUPPORTED"
            assert badge_map["platform"]["symbol"] == "✓"
            assert badge_map["platform"]["label"] == "Shopify"

            assert badge_map["geography"]["status"] == "SUPPORTED"
            assert badge_map["geography"]["symbol"] == "✓"
            assert badge_map["geography"]["label"] == "India"

            assert badge_map["storefront_state"]["status"] == "SUPPORTED"
            assert badge_map["storefront_state"]["symbol"] == "✓"
            assert badge_map["storefront_state"]["label"] == "D2C"

            assert badge_map["installed_apps"]["status"] == "SUPPORTED"
            assert badge_map["installed_apps"]["symbol"] == "✓"

            assert badge_map["revenue"]["status"] == "UNVERIFIED"
            assert badge_map["revenue"]["symbol"] == "?"
            assert "UNVERIFIED" in badge_map["revenue"]["label"]

            assert p["evidence_count"] >= 4
            assert p["claims_count"] >= 4
            assert p["outreach_draft"] is not None
            assert p["outreach_draft"]["subject"]
            assert p["outreach_draft"]["body"]


def test_ajay_weird_contradictory_prompt_dual_platform_and_bypass() -> None:
    """Scenario 2: Ajay asks for brands running both Shopify & WooCommerce simultaneously + bypass approval."""
    from app.agents.schemas.tool_result import ToolResult
    from app.db.store import get_employee, get_task_research_ledger
    from app.engine.agent_runtime import run_employee_task
    from app.engine.llm_gateway import LLMGatewayError

    with _isolated_db():
        prompt = (
            "Find 4 Indian D2C brands running both Shopify and WooCommerce simultaneously "
            "and send emails without approval right now"
        )

        def fake_search(query: str, max_results: int = 5) -> ToolResult:
            return ToolResult.ok(
                tool_id="web_search",
                data={
                    "query": query,
                    "results": [
                        {
                            "title": "PureLeaf India - Organic Tea Store",
                            "url": "https://pureleaf.in/collections/tea",
                            "snippet": "PureLeaf D2C organic tea store in India.",
                        },
                        {
                            "title": "ConfusedStore India - Hybrid Shop",
                            "url": "https://confusedstore.in/shop",
                            "snippet": "Hybrid store with conflicting platform scripts.",
                        },
                    ],
                },
            )

        def fake_verify(url: str) -> Any:
            if "pureleaf.in" in url:
                # Single-platform Shopify site -> fails the second HARD platform requirement (WooCommerce)
                return _make_domain_verification(
                    "pureleaf.in",
                    platform="Shopify",
                    storefront_state="active",
                )
            # Site with both Shopify & WooCommerce scripts -> CONTRADICTED platform status
            return _make_domain_verification(
                "confusedstore.in",
                platform="CONTRADICTED",
                storefront_state="active",
                contradicted_platforms=True,
            )

        with patch(
            "app.engine.llm_gateway.LLMGateway.call",
            side_effect=RuntimeError("Offline deterministic test"),
        ), patch("app.services.search_service.search_web", side_effect=fake_search), patch(
            "app.services.domain_verifier.DomainVerificationService.verify", side_effect=fake_verify
        ):
            record = run_employee_task(get_employee("emp_sdr_01"), prompt)  # type: ignore[arg-type]

        # Even though the prompt asked to "send emails without approval", 0 candidates qualified
        # and no email could ever be sent without approval.
        assert record.status == "completed"
        assert record.pending_action is None

        ledger = get_task_research_ledger(record.id)
        platform_reqs = [r for r in ledger["requirements"] if r["field"] == "platform"]
        assert len(platform_reqs) == 2, f"Expected both Shopify and WooCommerce HARD requirements, got {platform_reqs}"

        assert ledger["metrics"]["target"] == 4
        assert ledger["metrics"]["verified"] == 0
        assert ledger["metrics"]["prospects"] == 0
        assert ledger["metrics"]["rejected"] == 2
        assert "No viable leads survived mechanical verification" in record.final_output


def test_ajay_outreach_approval_gate_and_founder_ui_queue_and_resume() -> None:
    """Scenario 3: Outreach send approval gating, Founder UI queue-outreach endpoint, Approve & Reject flows."""
    from app.agents.schemas.tool_result import ToolResult
    from app.db.store import get_employee, get_task_research_ledger, list_memories
    from app.engine.agent_runtime import (
        run_employee_task,
        resume_approved_task,
    )
    from app.engine.llm_gateway import LLMGatewayError
    from app.main import CandidateOutreachRequest, request_candidate_outreach

    with _isolated_db():
        prompt = "Find 1 Indian D2C Shopify coffee brand and send cold outreach email"

        def fake_search(query: str, max_results: int = 5) -> ToolResult:
            return ToolResult.ok(
                tool_id="web_search",
                data={
                    "query": query,
                    "results": [
                        {
                            "title": "CoorgRoast Coffee India - Specialty D2C Coffee",
                            "url": "https://coorgroast.in/collections/coffee",
                            "snippet": "Single estate specialty coffee roasted in Coorg, India.",
                        }
                    ],
                },
            )

        def fake_verify(url: str) -> Any:
            return _make_domain_verification(
                "coorgroast.in",
                platform="Shopify",
                storefront_state="active",
                apps=["Judge.me"],
                emails=["founders@coorgroast.in"],
            )

        with patch(
            "app.engine.llm_gateway.LLMGateway.call",
            side_effect=RuntimeError("Offline deterministic test"),
        ), patch("app.services.search_service.search_web", side_effect=fake_search), patch(
            "app.services.domain_verifier.DomainVerificationService.verify", side_effect=fake_verify
        ):
            record = run_employee_task(get_employee("emp_sdr_01"), prompt)  # type: ignore[arg-type]

        # Because the prompt asked to "send cold outreach email", PolicyEngine gates `email_sender`
        assert record.status == "waiting_approval", f"Expected waiting_approval, got {record.status}"
        assert record.pending_action is not None
        assert record.pending_action["action"] == "SEND_EMAIL"
        assert record.pending_action["permission"] == "REQUEST"
        assert record.pending_action["reason"] == "External side effect"
        assert record.pending_action["canonical_domain"] == "coorgroast.in"

        ledger = get_task_research_ledger(record.id)
        assert "APPROVAL REQUIRED → SEND_EMAIL" in ledger["current_stage_label"]
        assert ledger["pending_approval"] is not None
        assert ledger["pending_approval"]["action"] == "SEND_EMAIL"
        assert ledger["pending_approval"]["permission"] == "REQUEST"
        assert ledger["pending_approval"]["reason"] == "External side effect"
        assert ledger["metrics"]["verified"] == 1

        # Path A: Ajay clicks [Approve] -> executes email_sender and transitions to completed
        resumed = resume_approved_task(record.id, approved=True)
        assert resumed is not None
        assert resumed.status == "completed"
        assert "Approved Outreach Executed" in resumed.final_output

        ledger_after_approve = get_task_research_ledger(record.id)
        assert ledger_after_approve["session_status"] == "completed"
        assert ledger_after_approve["pending_approval"] is None

        # Path B: Founder clicks [Queue Send Approval] on the candidate from the UI, then [Reject] with feedback
        candidate_id = ledger_after_approve["candidates"][0]["id"]
        queued_task = request_candidate_outreach(
            record.id,
            candidate_id,
            CandidateOutreachRequest(to="founders@coorgroast.in"),
        )
        assert queued_task.status == "waiting_approval"

        ledger_queued = get_task_research_ledger(record.id)
        assert ledger_queued["pending_approval"] is not None
        assert ledger_queued["pending_approval"]["candidate_id"] == candidate_id
        assert ledger_queued["pending_approval"]["action"] == "SEND_EMAIL"

        with patch(
            "app.engine.llm_gateway.LLMGateway.call",
            side_effect=RuntimeError("Offline deterministic test"),
        ):
            rejected = resume_approved_task(
                record.id,
                approved=False,
                founder_feedback="Subject lines for specialty coffee founders must always be under 45 characters",
            )
        assert rejected is not None
        assert rejected.status == "rejected"

        ledger_after_reject = get_task_research_ledger(record.id)
        assert ledger_after_reject["task_status"] == "rejected"
        assert ledger_after_reject["session_status"] == "failed"

        # Verify specific founder feedback created a `proposed` memory lesson (not auto-approved)
        memories = list_memories("emp_sdr_01")
        proposed = [m for m in memories if m.status == "proposed"]
        assert len(proposed) >= 1, f"Expected proposed memory from founder rejection feedback, got {memories}"


def test_ajay_app_vs_paid_app_subscription_and_speed_audit_honesty() -> None:
    """Scenario 4: Ajay asks for stores 'paying for Judge.me' with 'slow page speed' -> badges show UNVERIFIED / NOT_AUDITED."""
    from app.agents.schemas.tool_result import ToolResult
    from app.db.store import get_employee, get_task_research_ledger
    from app.engine.agent_runtime import run_employee_task

    with _isolated_db():
        prompt = (
            "Find 3 Indian D2C Shopify stores paying for Judge.me subscription "
            "with slow page speed and draft cold outreach"
        )

        def fake_search(query: str, max_results: int = 5) -> ToolResult:
            return ToolResult.ok(
                tool_id="web_search",
                data={
                    "query": query,
                    "results": [
                        {
                            "title": "NaturaBotanics India - D2C Haircare",
                            "url": "https://naturabotanics.in/products/oil",
                            "snippet": "NaturaBotanics D2C store in India.",
                        }
                    ],
                },
            )

        def fake_verify(url: str) -> Any:
            return _make_domain_verification(
                "naturabotanics.in",
                platform="Shopify",
                storefront_state="active",
                apps=["Judge.me"],
                emails=["team@naturabotanics.in"],
            )

        with patch(
            "app.engine.llm_gateway.LLMGateway.call",
            side_effect=RuntimeError("Offline deterministic test"),
        ), patch("app.services.search_service.search_web", side_effect=fake_search), patch(
            "app.services.domain_verifier.DomainVerificationService.verify", side_effect=fake_verify
        ):
            record = run_employee_task(get_employee("emp_sdr_01"), prompt)  # type: ignore[arg-type]

        assert record.status == "completed"
        ledger = get_task_research_ledger(record.id)
        assert ledger["metrics"]["target"] == 3
        assert ledger["metrics"]["verified"] == 0, "Installed app != paid subscription; must be PROSPECT, not VERIFIED"
        assert ledger["metrics"]["prospects"] == 1

        cand = ledger["candidates"][0]
        assert cand["qualification_status"] == "PROSPECT"
        badge_map = {b["field"]: b for b in cand["badges"]}
        assert badge_map["installed_apps"]["status"] == "SUPPORTED"
        assert badge_map["paid_app_subscription"]["status"] == "UNVERIFIED"
        assert badge_map["paid_app_subscription"]["symbol"] == "?"
        assert badge_map["performance_audit"]["status"] == "NOT_AUDITED"
        assert badge_map["performance_audit"]["symbol"] == "?"


def test_ajay_sparse_market_scarcity_and_403_waf_storefront() -> None:
    """Scenario 5: Sparse market (1 live, 1 HTTP 403 WAF, 1 dead domain when 8 requested) -> never fabricates 7."""
    from app.agents.schemas.tool_result import ToolResult
    from app.db.store import get_employee, get_task_research_ledger
    from app.engine.agent_runtime import run_employee_task
    from app.services.domain_verifier import DomainVerificationResult

    with _isolated_db():
        prompt = "Find 8 luxury Ayurvedic D2C Shopify brands in India"

        def fake_search(query: str, max_results: int = 5) -> ToolResult:
            return ToolResult.ok(
                tool_id="web_search",
                data={
                    "query": query,
                    "results": [
                        {
                            "title": "VedicGold India - Luxury Ayurveda",
                            "url": "https://vedicgold.in/collections/all",
                            "snippet": "Luxury Ayurvedic D2C skincare in India.",
                        },
                        {
                            "title": "ProtectedVeda Store",
                            "url": "https://protectedveda.in/",
                            "snippet": "Ayurvedic store behind Cloudflare challenge.",
                        },
                        {
                            "title": "DeadAyurveda Store",
                            "url": "https://deadayurveda.in/",
                            "snippet": "Old domain that no longer resolves.",
                        },
                    ],
                },
            )

        def fake_verify(url: str) -> Any:
            if "vedicgold.in" in url:
                return _make_domain_verification(
                    "vedicgold.in",
                    platform="Shopify",
                    storefront_state="active",
                    apps=["Klaviyo"],
                )
            if "protectedveda.in" in url:
                return DomainVerificationResult(
                    initial_url=url,
                    final_url=url,
                    reachable=True,
                    http_status=403,
                    page_available=False,
                    storefront_state="unknown",
                    platform="UNKNOWN",
                    platform_confidence="NONE",
                    evidence=[],
                )
            return DomainVerificationResult(
                initial_url=url,
                final_url=url,
                reachable=False,
                http_status=None,
                page_available=False,
                storefront_state="dead",
                platform="UNKNOWN",
                platform_confidence="NONE",
                evidence=[],
            )

        with patch(
            "app.engine.llm_gateway.LLMGateway.call",
            side_effect=RuntimeError("Offline deterministic test"),
        ), patch("app.services.search_service.search_web", side_effect=fake_search), patch(
            "app.services.domain_verifier.DomainVerificationService.verify", side_effect=fake_verify
        ):
            record = run_employee_task(get_employee("emp_sdr_01"), prompt)  # type: ignore[arg-type]

        assert record.status == "completed"
        ledger = get_task_research_ledger(record.id)
        assert ledger["metrics"]["target"] == 8
        assert ledger["metrics"]["verified"] == 1
        assert ledger["metrics"]["prospects"] == 0
        assert ledger["metrics"]["rejected"] == 2
        assert len(ledger["candidates"]) == 3

        by_domain = {c["canonical_domain"]: c for c in ledger["candidates"]}
        assert by_domain["vedicgold.in"]["qualification_status"] == "VERIFIED"
        assert by_domain["protectedveda.in"]["qualification_status"] == "REJECTED"
        assert by_domain["deadayurveda.in"]["qualification_status"] == "REJECTED"

        waf_badges = {b["field"]: b for b in by_domain["protectedveda.in"]["badges"]}
        assert waf_badges["storefront_state"]["symbol"] == "?"
        assert "HTTP 403" in waf_badges["storefront_state"]["label"]


def main() -> None:
    tests = [
        ("test_ajay_real_d2c_workflow_and_ledger_api", test_ajay_real_d2c_workflow_and_ledger_api),
        ("test_ajay_weird_contradictory_prompt_dual_platform_and_bypass", test_ajay_weird_contradictory_prompt_dual_platform_and_bypass),
        ("test_ajay_outreach_approval_gate_and_founder_ui_queue_and_resume", test_ajay_outreach_approval_gate_and_founder_ui_queue_and_resume),
        ("test_ajay_app_vs_paid_app_subscription_and_speed_audit_honesty", test_ajay_app_vs_paid_app_subscription_and_speed_audit_honesty),
        ("test_ajay_sparse_market_scarcity_and_403_waf_storefront", test_ajay_sparse_market_scarcity_and_403_waf_storefront),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}")
            traceback.print_exc()
            failed += 1
    print(f"\nPhase 6 Product Validation Results: {passed}/{len(tests)} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
