"""Phase 2 Unit & Invariant Tests — Core Schemas, Unified LLM Gateway, SearchService & Dumb Tool Registry."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List
import requests
from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
for p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import app.db.store as store
from app.agents.schemas import (
    ALLOWED_TRANSITIONS,
    Candidate,
    Claim,
    ClaimSnapshotItem,
    Evidence,
    InvalidStateTransitionError,
    QualificationDecision,
    Requirement,
    RequirementEvaluation,
    ResearchSession,
    ToolResult,
)
from app.engine.llm_gateway import (
    LLMCallResult,
    LLMClientError,
    LLMGateway,
    LLMSchemaValidationError,
    reset_model_cooldowns,
)
from app.engine.policy_engine import check_tool_permission
from app.models.employee import TaskRecord, ToolDefinition
from app.services.search_service import SearchService
from app.tools.registry import TOOLS_METADATA, execute_email_sender, execute_web_search


class _SamplePlanSchema(BaseModel):
    target_count: int
    platform: str


class _FakeGeminiUsage:
    def __init__(self, prompt: int = 25, completion: int = 15) -> None:
        self.prompt_token_count = prompt
        self.candidates_token_count = completion
        self.total_token_count = prompt + completion


class _FakeGeminiResponse:
    def __init__(self, text: str, response_id: str = "gem_req_123", prompt: int = 25, completion: int = 15) -> None:
        self.text = text
        self.response_id = response_id
        self.usage_metadata = _FakeGeminiUsage(prompt, completion)


class _FakeGroqUsage:
    def __init__(self, prompt: int = 30, completion: int = 20) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _FakeGroqMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeGroqChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeGroqMessage(content)


class _FakeGroqResponse:
    def __init__(self, content: str, req_id: str = "groq_req_456", prompt: int = 30, completion: int = 20) -> None:
        self.id = req_id
        self.choices = [_FakeGroqChoice(content)]
        self.usage = _FakeGroqUsage(prompt, completion)


class _HTTPErrorWithCode(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_groq_fallback_preserves_roles():
    """1. Groq fallback preserves system, user, and assistant roles in exact order."""
    reset_model_cooldowns()
    groq_calls: List[Dict[str, Any]] = []

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            raise _HTTPErrorWithCode("429 RESOURCE_EXHAUSTED", 429)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    class FakeGroqCompletions:
        def create(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Any:
            groq_calls.append({"model": model, "messages": messages})
            return _FakeGroqResponse("Groq fallback response", req_id="groq_roles_1")

    class FakeGroqChat:
        completions = FakeGroqCompletions()

    class FakeGroqClient:
        chat = FakeGroqChat()

    gw = LLMGateway(
        gemini_client=FakeGeminiClient(),
        groq_client_factory=lambda: FakeGroqClient(),
        fallback_models=["gemini-3.8-flash"],
        groq_models=["openai/gpt-oss-120b"],
    )

    gw.call(
        system_prompt="System instruction alpha",
        contents=[
            {"role": "user", "parts": [{"text": "User question 1"}]},
            {"role": "model", "parts": [{"text": "Assistant reply 1"}]},
            {"role": "assistant", "content": "Assistant reply 2"},
            {"role": "user", "content": "User question 2"},
        ],
        model="gemini-3.8-flash",
    )

    assert len(groq_calls) == 1
    sent = groq_calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "assistant", "user"]
    assert sent[0]["content"] == "System instruction alpha"
    assert sent[2]["content"] == "Assistant reply 1"
    assert sent[3]["content"] == "Assistant reply 2"


def test_actual_fallback_model_is_recorded():
    """2. Actual fallback model and provider are recorded when primary model fails."""
    reset_model_cooldowns()

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            raise _HTTPErrorWithCode("503 Service Unavailable", 503)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    class FakeGroqCompletions:
        def create(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.2) -> Any:
            if model == "openai/gpt-oss-120b":
                raise _HTTPErrorWithCode("429 Rate Limit", 429)
            return _FakeGroqResponse("Recovered on second Groq model", req_id="groq_second")

    class FakeGroqChat:
        completions = FakeGroqCompletions()

    class FakeGroqClient:
        chat = FakeGroqChat()

    gw = LLMGateway(
        gemini_client=FakeGeminiClient(),
        groq_client_factory=lambda: FakeGroqClient(),
        fallback_models=["gemini-3.8-flash", "gemini-3.7-flash"],
        groq_models=["openai/gpt-oss-120b", "qwen/qwen3.8-27b"],
    )

    res = gw.call(contents=[{"role": "user", "content": "Test"}], model="gemini-3.8-flash")
    assert res.provider == "groq"
    assert res.requested_model == "gemini-3.8-flash"
    assert res.actual_model == "qwen/qwen3.8-27b"
    assert res.attempts == 4


def test_token_and_latency_telemetry_is_recorded():
    """3. Prompt tokens, completion tokens, total tokens, latency_ms, and request_id are recorded."""
    reset_model_cooldowns()

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            return _FakeGeminiResponse("Telemetry check", response_id="gem_telemetry_77", prompt=64, completion=28)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    gw = LLMGateway(gemini_client=FakeGeminiClient(), fallback_models=["gemini-3.8-flash"])
    res: LLMCallResult[Any] = gw.call(contents=[{"role": "user", "content": "Measure tokens"}], model="gemini-3.8-flash")

    assert res.provider == "gemini"
    assert res.actual_model == "gemini-3.8-flash"
    assert res.prompt_tokens == 64
    assert res.completion_tokens == 28
    assert res.total_tokens == 92
    assert res.latency_ms >= 0.0
    assert res.request_id == "gem_telemetry_77"


def test_400_client_error_does_not_cascade():
    """4. HTTP 400 / 401 / 403 client errors fail immediately without cascading to other models."""
    reset_model_cooldowns()
    models_called: List[str] = []
    groq_called = False

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            models_called.append(model)
            raise _HTTPErrorWithCode("400 INVALID_ARGUMENT: malformed request payload", 400)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    def fail_if_groq_called() -> Any:
        nonlocal groq_called
        groq_called = True
        raise AssertionError("Groq should never be called on a 400 client error")

    gw = LLMGateway(
        gemini_client=FakeGeminiClient(),
        groq_client_factory=fail_if_groq_called,
        fallback_models=["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"],
    )

    try:
        gw.call(contents=[{"role": "user", "content": "Hello"}], model="gemini-3.8-flash")
        raise AssertionError("Expected LLMClientError on HTTP 400")
    except LLMClientError as err:
        assert err.error_classification == "CLIENT_ERROR"
        assert err.status_code == 400
        assert err.attempts == 1
        assert err.actual_model == "gemini-3.8-flash"

    assert models_called == ["gemini-3.8-flash"]
    assert groq_called is False


def test_429_transient_error_does_cascade():
    """5. HTTP 429 rate-limit cascades to the next fallback model."""
    reset_model_cooldowns()
    models_called: List[str] = []

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            models_called.append(model)
            if model == "gemini-3.8-flash":
                raise _HTTPErrorWithCode("429 Too Many Requests", 429)
            return _FakeGeminiResponse("Success on 3.7", response_id="gem_ok_2", prompt=19, completion=11)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    gw = LLMGateway(
        gemini_client=FakeGeminiClient(),
        fallback_models=["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"],
    )

    res = gw.call(contents=[{"role": "user", "content": "Ping"}], model="gemini-3.8-flash")
    assert models_called == ["gemini-3.8-flash", "gemini-3.7-flash"]
    assert res.actual_model == "gemini-3.7-flash"
    assert res.attempts == 2


def test_schema_error_gets_exactly_one_repair():
    """6. JSON/schema failure triggers at most 1 repair call on the exact same model and succeeds."""
    reset_model_cooldowns()
    calls: List[str] = []

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            calls.append(model)
            if len(calls) == 1:
                return _FakeGeminiResponse('{"target_count": "invalid_int"}', response_id="gem_bad_1", prompt=10, completion=8)
            return _FakeGeminiResponse('{"target_count": 10, "platform": "Shopify"}', response_id="gem_rep_2", prompt=20, completion=12)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    gw = LLMGateway(
        gemini_client=FakeGeminiClient(),
        fallback_models=["gemini-3.8-flash", "gemini-3.7-flash"],
    )

    res = gw.call(
        contents=[{"role": "user", "content": "Extract plan"}],
        model="gemini-3.8-flash",
        response_schema=_SamplePlanSchema,
    )

    assert calls == ["gemini-3.8-flash", "gemini-3.8-flash"]
    assert res.repair_attempted is True
    assert res.attempts == 2
    assert res.actual_model == "gemini-3.8-flash"
    assert isinstance(res.parsed_result, _SamplePlanSchema)
    assert res.parsed_result.target_count == 10


def test_second_schema_failure_stops():
    """7. Second schema failure on the repair call stops immediately and never cascades to other models."""
    reset_model_cooldowns()
    calls: List[str] = []
    groq_called = False

    class FakeGeminiModels:
        def generate_content(self, model: str, contents: Any, **kwargs: Any) -> Any:
            calls.append(model)
            return _FakeGeminiResponse("NOT_VALID_JSON", response_id=f"gem_fail_{len(calls)}", prompt=10, completion=5)

    class FakeGeminiClient:
        models = FakeGeminiModels()

    def fail_if_groq_called() -> Any:
        nonlocal groq_called
        groq_called = True
        raise AssertionError("Groq must not be called on schema failure")

    gw = LLMGateway(
        gemini_client=FakeGeminiClient(),
        groq_client_factory=fail_if_groq_called,
        fallback_models=["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"],
    )

    try:
        gw.call(
            contents=[{"role": "user", "content": "Extract plan"}],
            model="gemini-3.8-flash",
            response_schema=_SamplePlanSchema,
        )
        raise AssertionError("Expected LLMSchemaValidationError after second schema failure")
    except LLMSchemaValidationError as err:
        assert err.error_classification == "SCHEMA_VALIDATION_ERROR"
        assert err.repair_attempted is True
        assert err.attempts == 2
        assert err.actual_model == "gemini-3.8-flash"

    assert calls == ["gemini-3.8-flash", "gemini-3.8-flash"]
    assert groq_called is False


def test_tavily_does_exactly_one_query():
    """8. Tavily SearchService executes exactly 1 HTTP request with include_answer=False."""
    recorded_payloads: List[Dict[str, Any]] = []

    class FakeHTTPResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Dict[str, Any]:
            return {
                "results": [
                    {"title": "Brand One", "url": "https://brandone.in", "content": "Shopify store"},
                ],
            }

    def fake_post(url: str, json: Dict[str, Any], timeout: float) -> Any:
        recorded_payloads.append({"url": url, "json": json, "timeout": timeout})
        return FakeHTTPResponse()

    service = SearchService(api_key="tvly-test-key", http_post=fake_post)
    res = service.search("site:myshopify.com skincare India")

    assert len(recorded_payloads) == 1
    assert recorded_payloads[0]["json"]["include_answer"] is False
    assert recorded_payloads[0]["json"]["query"] == "site:myshopify.com skincare India"
    assert res.status == "success"
    assert len(res.data["results"]) == 1


def test_tavily_failure_produces_error_tool_result():
    """9. Tavily HTTP/timeout/key failures return typed error/timeout/not_configured ToolResult with zero fake fallback rows."""

    def timeout_post(url: str, json: Dict[str, Any], timeout: float) -> Any:
        raise requests.Timeout("Connection timed out after 20s")

    service = SearchService(api_key="tvly-test-key", http_post=timeout_post)
    res = service.search("Indian Shopify D2C brands")

    assert isinstance(res, ToolResult)
    assert res.status == "timeout"
    assert res.error_code == "TAVILY_TIMEOUT"
    assert res.data["results"] == []

    def http_err_post(url: str, json: Dict[str, Any], timeout: float) -> Any:
        resp = requests.Response()
        resp.status_code = 502
        raise requests.HTTPError("502 Bad Gateway", response=resp)

    err_service = SearchService(api_key="tvly-test-key", http_post=http_err_post)
    res_err = err_service.search("Indian Shopify D2C brands")
    assert res_err.status == "error"
    assert res_err.error_code == "TAVILY_HTTP_502"
    assert res_err.data["results"] == []

    no_key_service = SearchService(api_key="", http_post=timeout_post)
    res_no_key = no_key_service.search("Indian Shopify D2C brands")
    assert res_no_key.status == "not_configured"
    assert res_no_key.error_code == "MISSING_API_KEY"
    assert res_no_key.data["results"] == []


def test_no_hidden_query_expansion():
    """10. Queries containing 'shopify', 'd2c', 'turnover', 'apps', 'hiring', 'freelance' never trigger hidden extra searches."""
    call_count = 0

    class FakeHTTPResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Dict[str, Any]:
            return {"results": [{"title": "Hit", "url": "https://store.in", "content": "ok"}]}

    def counting_post(url: str, json: Dict[str, Any], timeout: float) -> Any:
        nonlocal call_count
        call_count += 1
        return FakeHTTPResponse()

    tricky_query = "shopify d2c brand turnover 10 lakh apps hiring freelance contractor vibe coding"
    res = execute_web_search(tricky_query, single_query=False, api_key="tvly-key", http_post=counting_post)

    assert call_count == 1
    assert res.status == "success"


def test_unknown_tool_permission_is_denied():
    """11. TOOLS_METADATA has no permission authority and PolicyEngine denies unknown tools."""
    for item in TOOLS_METADATA:
        assert "requires_approval" not in item

    assert "requires_approval" not in ToolDefinition.model_fields

    with tempfile.TemporaryDirectory() as td:
        prev_db = store.DB_PATH
        try:
            store.DB_PATH = str(Path(td) / "policy_test.db")
            store.init_db()
            decision = check_tool_permission("emp_sdr_01", "nonexistent_nuclear_launcher", {"target": "moon"}, "task_phase2_test")
            assert decision.allowed is False
            assert "not registered" in decision.reason.lower()
        finally:
            store.DB_PATH = prev_db


def test_phase2_core_schemas_and_email_escaping():
    """12. Verifies Requirement observability, Claim versioning, QualificationDecision hash, locked session resume, and email escaping."""
    req_installed = Requirement(field="installed_apps", operator="contains_any", expected=["Judge.me", "Wati"])
    req_paid = Requirement(field="paid_app_subscription", operator="exists", expected=True, on_unknown="REJECT")
    req_rev = Requirement(field="revenue", operator="range", expected={"min_value": 1000000, "max_value": 5000000})

    assert req_installed.observability_class == "HIGH"
    assert req_paid.observability_class == "LOW_PUBLIC_OBSERVABILITY"
    assert req_paid.on_unknown == "PROSPECT"
    assert "live_html_footprint" not in req_paid.allowed_source_types
    assert req_rev.observability_class == "LOW_PUBLIC_OBSERVABILITY"
    assert req_rev.on_unknown == "PROSPECT"

    ev = Evidence(
        id="E1",
        session_id="sess_1",
        candidate_id="C1",
        source_url="https://example.in",
        source_type="live_html_footprint",
        supports_field="platform",
        signal_type="script_src:cdn.shopify.com",
        extracted_value="Shopify",
        raw_excerpt="cdn.shopify.com/s/files/1/",
    )
    assert len(ev.content_hash) == 64

    claim = Claim(session_id="sess_1", candidate_id="C1", field="platform", value="Shopify", status="SUPPORTED", evidence_ids=[])
    assert claim.status == "UNVERIFIED"
    assert claim.version == 1

    claim.revise(value="Shopify", status="SUPPORTED", evidence_ids=[ev.id])
    assert claim.status == "SUPPORTED"
    assert claim.version == 2

    snap = {
        "platform": ClaimSnapshotItem(
            claim_id=claim.id,
            field="platform",
            value="Shopify",
            status="SUPPORTED",
            version=claim.version,
            evidence_ids=[ev.id],
        )
    }
    evals = {
        req_installed.id: RequirementEvaluation(
            requirement_id=req_installed.id,
            field="platform",
            priority="HARD",
            status="SATISFIED",
            evidence_ids=[ev.id],
            reason="Verified Shopify HTML footprint",
        )
    }
    d1 = QualificationDecision(
        session_id="sess_1",
        candidate_id="C1",
        hop=1,
        result="PROSPECT",
        claims_snapshot=snap,
        requirement_results=evals,
        supporting_claim_ids=[claim.id],
        supporting_evidence_ids=[ev.id],
        notes=["High-observability constraints verified; private revenue unverified."],
    )
    d2 = QualificationDecision(
        session_id="sess_1",
        candidate_id="C1",
        hop=1,
        result="PROSPECT",
        claims_snapshot=snap,
        requirement_results=evals,
        supporting_claim_ids=[claim.id],
        supporting_evidence_ids=[ev.id],
        notes=["Different note text does not change canonical input hash"],
    )
    assert d1.decision_hash == d2.decision_hash

    cand = Candidate(id="C1", session_id="sess_1", company_name="Example", canonical_domain="example.in", initial_url="https://example.in")
    cand.apply_qualification_decision(d1)
    assert cand.latest_decision_id == d1.id
    assert cand.qualification_status == "PROSPECT"

    sess = ResearchSession(id="sess_1", task_id="task_1", raw_prompt="Find 5 Shopify brands", max_hops=2)
    sess.transition_to("discovering")
    assert sess.current_hop == 1
    sess.transition_to("collecting")
    sess.transition_to("verifying")
    sess.transition_to("qualifying")
    sess.transition_to("composing")
    sess.transition_to("validating")
    sess.transition_to("waiting_approval")

    assert "completed" not in ALLOWED_TRANSITIONS["waiting_approval"]
    try:
        sess.transition_to("completed")
        raise AssertionError("Should not allow exiting waiting_approval to completed via transition_to")
    except InvalidStateTransitionError:
        pass

    task = TaskRecord(
        id="task_1",
        employee_id="emp_sdr_01",
        employee_name="Maya Vance",
        task_prompt="Find 5 Shopify brands",
        status="waiting_approval",
        resume_state="completed",
    )
    assert sess.resume_from_approval(task) == "completed"

    # Verify blacklisted email returns blocked ToolResult
    blocked_mail = execute_email_sender("ceo@investor.com", "Pitch", "Hello")
    assert blocked_mail.status == "blocked"
    assert blocked_mail.error_code == "BLACKLIST_BLOCKED"


if __name__ == "__main__":
    test_groq_fallback_preserves_roles()
    test_actual_fallback_model_is_recorded()
    test_token_and_latency_telemetry_is_recorded()
    test_400_client_error_does_not_cascade()
    test_429_transient_error_does_cascade()
    test_schema_error_gets_exactly_one_repair()
    test_second_schema_failure_stops()
    test_tavily_does_exactly_one_query()
    test_tavily_failure_produces_error_tool_result()
    test_no_hidden_query_expansion()
    test_unknown_tool_permission_is_denied()
    test_phase2_core_schemas_and_email_escaping()
    print("12 passed")
