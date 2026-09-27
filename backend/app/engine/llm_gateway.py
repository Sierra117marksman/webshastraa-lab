"""Unified LLM Gateway for Maya v2 (Rev 3 Frozen Contract — Phase 2).

Enforces:
1. Typed `LLMCallResult[T]` with provider, actual_model, latency_ms, token telemetry,
   raw_output, parsed_result, request_id, and error_classification.
2. Strict 3-way error behavior:
   - 400 / 401 / 403 -> fail immediately (LLMClientError, no cascade)
   - 429 / 502 / 503 / 504 / timeout -> controlled model/provider fallback
   - JSON / schema validation error -> max 1 same-model repair, then fail (LLMSchemaValidationError, no model cascade)
3. Exact preservation of `system`, `user`, and `assistant` roles across Gemini and Groq.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Generic, List, Literal, Optional, Sequence, Tuple, Type, TypeVar, Union
import uuid
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

ProviderName = Literal["gemini", "groq"]
MessageRole = Literal["system", "user", "assistant"]
ErrorClassification = Literal[
    "CLIENT_ERROR",
    "TRANSIENT_PROVIDER_ERROR",
    "SCHEMA_VALIDATION_ERROR",
]

FALLBACK_MODELS: List[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

GROQ_MODELS: List[str] = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
]

_MODEL_COOLDOWN_UNTIL: Dict[str, float] = {}


def reset_model_cooldowns() -> None:
    """Clear in-memory model cooldowns (used by tests)."""
    _MODEL_COOLDOWN_UNTIL.clear()


def get_groq_api_key() -> str:
    return (os.getenv("GROQ_API_KEY") or "").strip()


class LLMMessage(BaseModel):
    """Canonical role-preserving message turn."""
    role: MessageRole
    content: str


class LLMCallResult(BaseModel, Generic[T]):
    """Unified typed telemetry and parsed output envelope for all LLM calls."""
    provider: ProviderName
    requested_model: str
    actual_model: str
    latency_ms: float = Field(ge=0.0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    raw_output: str
    parsed_result: Optional[Any] = None
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    error_classification: Optional[ErrorClassification] = None
    repair_attempted: bool = False
    attempts: int = Field(default=1, ge=1)

    @property
    def text(self) -> str:
        """Backward-compatible property for callers reading `response.text`."""
        return self.raw_output

    @property
    def error_class(self) -> Optional[ErrorClassification]:
        return self.error_classification


class LLMGatewayError(RuntimeError):
    """Base structured exception raised by LLMGateway."""

    def __init__(
        self,
        message: str,
        *,
        error_classification: ErrorClassification,
        provider: ProviderName,
        requested_model: str,
        actual_model: str,
        request_id: str,
        status_code: Optional[int] = None,
        repair_attempted: bool = False,
        attempts: int = 1,
        latency_ms: float = 0.0,
        raw_output: str = "",
    ) -> None:
        super().__init__(message)
        self.error_classification = error_classification
        self.error_class = error_classification
        self.provider = provider
        self.requested_model = requested_model
        self.actual_model = actual_model
        self.request_id = request_id
        self.status_code = status_code
        self.repair_attempted = repair_attempted
        self.attempts = attempts
        self.latency_ms = latency_ms
        self.raw_output = raw_output


class LLMClientError(LLMGatewayError):
    """Raised on 400 / 401 / 403 errors. Never cascades to other models."""


class LLMTransientProviderError(LLMGatewayError):
    """Raised when all fallback models/providers fail with 429 / 502 / 503 / 504 / timeout."""


class LLMSchemaValidationError(LLMGatewayError):
    """Raised when structured output fails schema validation after 1 same-model repair."""


def normalize_messages(
    contents: Optional[Sequence[Union[LLMMessage, Dict[str, Any], str]]] = None,
    *,
    system_prompt: Optional[str] = None,
) -> List[LLMMessage]:
    """Normalize heterogeneous message formats while preserving system, user, and assistant roles."""
    normalized: List[LLMMessage] = []
    if system_prompt and system_prompt.strip():
        normalized.append(LLMMessage(role="system", content=system_prompt.strip()))

    for item in contents or []:
        if isinstance(item, LLMMessage):
            normalized.append(item)
            continue
        if isinstance(item, str):
            if item.strip():
                normalized.append(LLMMessage(role="user", content=item))
            continue
        if isinstance(item, dict):
            raw_role = str(item.get("role") or "user").strip().lower()
            if raw_role == "system":
                role: MessageRole = "system"
            elif raw_role in ("assistant", "model"):
                role = "assistant"
            else:
                role = "user"

            text = ""
            if "content" in item and item["content"] is not None:
                text = str(item["content"])
            elif "parts" in item and isinstance(item["parts"], list):
                parts_text: List[str] = []
                for part in item["parts"]:
                    if isinstance(part, dict) and part.get("text") is not None:
                        parts_text.append(str(part["text"]))
                    elif isinstance(part, str):
                        parts_text.append(part)
                text = "".join(parts_text)

            if text:
                normalized.append(LLMMessage(role=role, content=text))

    return normalized


def to_groq_messages(messages: Sequence[LLMMessage]) -> List[Dict[str, str]]:
    """Convert normalized messages to OpenAI/Groq chat format preserving system, user, and assistant roles."""
    return [{"role": m.role, "content": m.content} for m in messages if m.content]


def to_gemini_payload(messages: Sequence[LLMMessage]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Convert normalized messages to Gemini system_instruction + contents list."""
    system_chunks: List[str] = []
    gemini_contents: List[Dict[str, Any]] = []
    for m in messages:
        if not m.content:
            continue
        if m.role == "system":
            system_chunks.append(m.content)
        elif m.role == "assistant":
            gemini_contents.append({"role": "model", "parts": [{"text": m.content}]})
        else:
            gemini_contents.append({"role": "user", "parts": [{"text": m.content}]})

    system_instruction = "\n\n".join(system_chunks) if system_chunks else None
    if not gemini_contents and system_instruction:
        # Gemini requires at least one content turn if only system was passed
        gemini_contents.append({"role": "user", "parts": [{"text": system_instruction}]})
        system_instruction = None
    return system_instruction, gemini_contents


def classify_provider_exception(exc: Exception) -> Tuple[ErrorClassification, Optional[int]]:
    """Classify provider exception into CLIENT_ERROR (400/401/403) vs TRANSIENT_PROVIDER_ERROR (429/502/503/504/timeout)."""
    status_code: Optional[int] = None
    for attr in ("status_code", "code", "http_status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            status_code = val
            break

    msg = str(exc)
    if status_code is None:
        match = re.search(r"\b(400|401|403|429|502|503|504)\b", msg)
        if match:
            status_code = int(match.group(1))

    if status_code in (400, 401, 403):
        return "CLIENT_ERROR", status_code

    msg_upper = msg.upper()
    if any(
        tok in msg_upper
        for tok in (
            "INVALID_ARGUMENT",
            "PERMISSION_DENIED",
            "UNAUTHENTICATED",
            "INVALID_API_KEY",
            "API_KEY_INVALID",
            "API KEY NOT VALID",
            "NO API KEY",
            "BAD REQUEST",
            "UNAUTHORIZED",
            "FORBIDDEN",
        )
    ):
        return "CLIENT_ERROR", status_code or 401

    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "TRANSIENT_PROVIDER_ERROR", status_code or 504

    if status_code in (429, 502, 503, 504) or any(
        tok in msg_upper
        for tok in (
            "RESOURCE_EXHAUSTED",
            "QUOTA",
            "RATE_LIMIT",
            "RATE LIMIT",
            "UNAVAILABLE",
            "HIGH DEMAND",
            "DEADLINE_EXCEEDED",
            "TIMEOUT",
            "TIMED OUT",
            "BAD GATEWAY",
            "GATEWAY TIMEOUT",
            "OVERLOADED",
        )
    ):
        return "TRANSIENT_PROVIDER_ERROR", status_code

    # Default unexpected transport/provider exceptions to transient so fallback can attempt recovery
    return "TRANSIENT_PROVIDER_ERROR", status_code


def _extract_gemini_usage(res: Any, raw_text: str, messages: Sequence[LLMMessage]) -> Tuple[int, int, int, str]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    usage = getattr(res, "usage_metadata", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        total_tokens = int(getattr(usage, "total_token_count", 0) or (prompt_tokens + completion_tokens))
    if prompt_tokens == 0 and messages:
        prompt_tokens = max(1, sum(len(m.content) for m in messages) // 4)
    if completion_tokens == 0 and raw_text:
        completion_tokens = max(1, len(raw_text) // 4)
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    req_id = (
        getattr(res, "response_id", None)
        or getattr(res, "id", None)
        or f"gem_{uuid.uuid4().hex[:12]}"
    )
    return prompt_tokens, completion_tokens, total_tokens, str(req_id)


def _extract_groq_usage(res: Any, raw_text: str, messages: Sequence[LLMMessage]) -> Tuple[int, int, int, str]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    usage = getattr(res, "usage", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens))
    if prompt_tokens == 0 and messages:
        prompt_tokens = max(1, sum(len(m.content) for m in messages) // 4)
    if completion_tokens == 0 and raw_text:
        completion_tokens = max(1, len(raw_text) // 4)
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    req_id = getattr(res, "id", None) or f"groq_{uuid.uuid4().hex[:12]}"
    return prompt_tokens, completion_tokens, total_tokens, str(req_id)


def _strip_markdown_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_and_validate_schema(raw_output: str, schema: Type[T]) -> T:
    cleaned = _strip_markdown_fences(raw_output)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as je:
        # Check if there is a JSON object embedded in text
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            payload = json.loads(cleaned[start : end + 1])
        else:
            raise je
    return schema.model_validate(payload)


class LLMGateway:
    """Unified gateway for Gemini primary cascade and Groq LPU fallback."""

    def __init__(
        self,
        gemini_client: Any = None,
        groq_client_factory: Optional[Callable[[], Any]] = None,
        fallback_models: Optional[List[str]] = None,
        groq_models: Optional[List[str]] = None,
    ) -> None:
        self._gemini_client = gemini_client
        self._groq_client_factory = groq_client_factory
        self.fallback_models = list(fallback_models or FALLBACK_MODELS)
        self.groq_models = list(groq_models or GROQ_MODELS)

    def _get_gemini_client(self) -> Any:
        if self._gemini_client is not None:
            return self._gemini_client
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        self._gemini_client = genai.Client(api_key=api_key)
        return self._gemini_client

    def _get_groq_client(self) -> Optional[Any]:
        if self._groq_client_factory is not None:
            return self._groq_client_factory()
        groq_api_key = get_groq_api_key()
        if not groq_api_key:
            return None
        from groq import Groq
        return Groq(api_key=groq_api_key)

    def _invoke_gemini_single(
        self,
        model_name: str,
        messages: Sequence[LLMMessage],
        requested_model: str,
    ) -> LLMCallResult[Any]:
        client = self._get_gemini_client()
        system_instruction, gemini_contents = to_gemini_payload(messages)
        t0 = time.perf_counter()
        gen_fn = client.models.generate_content

        if system_instruction:
            try:
                sig = inspect.signature(gen_fn)
                accepts_config = "config" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                )
            except Exception:
                accepts_config = True

            if accepts_config:
                res = gen_fn(
                    model=model_name,
                    contents=gemini_contents,
                    config={"system_instruction": system_instruction},
                )
            else:
                merged = [{"role": "system", "parts": [{"text": system_instruction}]}] + gemini_contents
                res = gen_fn(model=model_name, contents=merged)
        else:
            res = gen_fn(model=model_name, contents=gemini_contents)

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        raw_text = (getattr(res, "text", None) or "").strip()
        if not raw_text:
            raise RuntimeError(f"Gemini model '{model_name}' returned empty response text")

        prompt_tok, comp_tok, total_tok, req_id = _extract_gemini_usage(res, raw_text, messages)
        return LLMCallResult(
            provider="gemini",
            requested_model=requested_model,
            actual_model=model_name,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
            total_tokens=total_tok,
            raw_output=raw_text,
            request_id=req_id,
        )

    def _invoke_groq_single(
        self,
        model_name: str,
        messages: Sequence[LLMMessage],
        requested_model: str,
        groq_client: Any,
    ) -> LLMCallResult[Any]:
        groq_messages = to_groq_messages(messages)
        if not groq_messages:
            raise LLMClientError(
                "Cannot invoke Groq with empty message list",
                error_classification="CLIENT_ERROR",
                provider="groq",
                requested_model=requested_model,
                actual_model=model_name,
                request_id=f"groq_err_{uuid.uuid4().hex[:8]}",
                status_code=400,
            )

        t0 = time.perf_counter()
        res = groq_client.chat.completions.create(
            model=model_name,
            messages=groq_messages,
            temperature=0.2,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        raw_text = (res.choices[0].message.content or "").strip()
        if not raw_text:
            raise RuntimeError(f"Groq model '{model_name}' returned empty response text")

        prompt_tok, comp_tok, total_tok, req_id = _extract_groq_usage(res, raw_text, messages)
        return LLMCallResult(
            provider="groq",
            requested_model=requested_model,
            actual_model=model_name,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tok,
            completion_tokens=comp_tok,
            total_tokens=total_tok,
            raw_output=raw_text,
            request_id=req_id,
        )

    def _execute_transport_with_fallback(
        self,
        messages: Sequence[LLMMessage],
        requested_model: str,
    ) -> Tuple[LLMCallResult[Any], Optional[Any], int]:
        """Run one transport round across Gemini cascade -> Groq fallback.

        Immediately aborts without cascading on 400/401/403 (CLIENT_ERROR).
        Cascades only on 429/502/503/504/timeout (TRANSIENT_PROVIDER_ERROR).
        """
        models_to_try = [requested_model] + [m for m in self.fallback_models if m != requested_model]
        now = time.time()
        attempts = 0
        last_exc: Optional[Exception] = None
        last_status: Optional[int] = None
        last_provider: ProviderName = "gemini"
        last_model: str = requested_model

        for current_model in models_to_try:
            cooldown_until = _MODEL_COOLDOWN_UNTIL.get(current_model, 0.0)
            if now < cooldown_until:
                continue

            attempts += 1
            last_provider = "gemini"
            last_model = current_model
            try:
                res = self._invoke_gemini_single(current_model, messages, requested_model)
                res.attempts = attempts
                return res, None, attempts
            except LLMGatewayError:
                raise
            except Exception as exc:
                last_exc = exc
                err_class, status_code = classify_provider_exception(exc)
                last_status = status_code

                # Rule 1: 400 / 401 / 403 -> fail immediately without cascading
                if err_class == "CLIENT_ERROR":
                    raise LLMClientError(
                        f"Non-retryable client error ({status_code}) on {current_model}: {exc}",
                        error_classification="CLIENT_ERROR",
                        provider="gemini",
                        requested_model=requested_model,
                        actual_model=current_model,
                        request_id=f"err_{uuid.uuid4().hex[:12]}",
                        status_code=status_code,
                        attempts=attempts,
                    ) from exc

                # Rule 2: 429 / 502 / 503 / 504 / timeout -> record cooldown and cascade
                err_msg = str(exc)
                if status_code == 429 or "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                    is_daily = "PerDay" in err_msg or "free_tier_requests" in err_msg
                    _MODEL_COOLDOWN_UNTIL[current_model] = time.time() + (600.0 if is_daily else 60.0)
                elif status_code in (502, 503, 504) or "503" in err_msg or "UNAVAILABLE" in err_msg:
                    _MODEL_COOLDOWN_UNTIL[current_model] = time.time() + 120.0

                logger.warning(
                    f"[LLMGateway] Transient error on Gemini/{current_model} ({str(exc)[:100]}). Cascading..."
                )
                continue

        # Fallback to Groq LPU
        groq_client = self._get_groq_client()
        if groq_client is not None:
            for groq_model in self.groq_models:
                attempts += 1
                last_provider = "groq"
                last_model = groq_model
                try:
                    res = self._invoke_groq_single(groq_model, messages, requested_model, groq_client)
                    res.attempts = attempts
                    return res, groq_client, attempts
                except LLMGatewayError:
                    raise
                except Exception as g_exc:
                    last_exc = g_exc
                    err_class, status_code = classify_provider_exception(g_exc)
                    last_status = status_code
                    if err_class == "CLIENT_ERROR":
                        raise LLMClientError(
                            f"Non-retryable client error ({status_code}) on Groq/{groq_model}: {g_exc}",
                            error_classification="CLIENT_ERROR",
                            provider="groq",
                            requested_model=requested_model,
                            actual_model=groq_model,
                            request_id=f"err_{uuid.uuid4().hex[:12]}",
                            status_code=status_code,
                            attempts=attempts,
                        ) from g_exc
                    logger.warning(
                        f"[LLMGateway] Transient error on Groq/{groq_model} ({str(g_exc)[:100]}). Trying next..."
                    )
                    continue

        raise LLMTransientProviderError(
            f"All Gemini and Groq fallback models exhausted. Last error: {last_exc}",
            error_classification="TRANSIENT_PROVIDER_ERROR",
            provider=last_provider,
            requested_model=requested_model,
            actual_model=last_model,
            request_id=f"err_{uuid.uuid4().hex[:12]}",
            status_code=last_status,
            attempts=max(1, attempts),
        ) from last_exc

    def call(
        self,
        contents: Optional[Sequence[Union[LLMMessage, Dict[str, Any], str]]] = None,
        *,
        model: str = "gemini-3.8-flash",
        system_prompt: Optional[str] = None,
        response_schema: Optional[Type[T]] = None,
    ) -> LLMCallResult[T]:
        """Execute an LLM call with unified telemetry and optional 1-shot same-model schema repair."""
        messages = normalize_messages(contents, system_prompt=system_prompt)
        if not messages:
            raise LLMClientError(
                "LLMGateway.call received no messages",
                error_classification="CLIENT_ERROR",
                provider="gemini",
                requested_model=model,
                actual_model=model,
                request_id=f"err_{uuid.uuid4().hex[:12]}",
                status_code=400,
            )

        initial_res, groq_client, attempts = self._execute_transport_with_fallback(messages, model)

        if response_schema is None:
            return initial_res

        # Validate structured JSON against response_schema
        try:
            parsed = _parse_and_validate_schema(initial_res.raw_output, response_schema)
            initial_res.parsed_result = parsed
            return initial_res
        except (json.JSONDecodeError, ValidationError, ValueError) as first_schema_err:
            logger.warning(
                f"[LLMGateway Schema Repair] {initial_res.provider}/{initial_res.actual_model} returned "
                f"invalid schema ({first_schema_err}). Attempting 1 same-model repair..."
            )

            # Rule 3: Max 1 same-model repair on the exact same provider + actual_model (never cascade models)
            repair_messages = list(messages) + [
                LLMMessage(role="assistant", content=initial_res.raw_output),
                LLMMessage(
                    role="user",
                    content=(
                        f"Your previous response failed JSON/schema validation with error:\n"
                        f"{first_schema_err}\n\n"
                        f"Return ONLY valid raw JSON conforming to schema '{response_schema.__name__}'."
                    ),
                ),
            ]

            attempts += 1
            if initial_res.provider == "gemini":
                repair_res = self._invoke_gemini_single(initial_res.actual_model, repair_messages, model)
            else:
                active_groq = groq_client or self._get_groq_client()
                if active_groq is None:
                    raise LLMSchemaValidationError(
                        f"Schema repair unavailable on Groq/{initial_res.actual_model}",
                        error_classification="SCHEMA_VALIDATION_ERROR",
                        provider=initial_res.provider,
                        requested_model=model,
                        actual_model=initial_res.actual_model,
                        request_id=initial_res.request_id,
                        repair_attempted=True,
                        attempts=attempts,
                        latency_ms=initial_res.latency_ms,
                        raw_output=initial_res.raw_output,
                    ) from first_schema_err
                repair_res = self._invoke_groq_single(initial_res.actual_model, repair_messages, model, active_groq)

            total_latency = round(initial_res.latency_ms + repair_res.latency_ms, 3)
            total_prompt = initial_res.prompt_tokens + repair_res.prompt_tokens
            total_comp = initial_res.completion_tokens + repair_res.completion_tokens
            total_tok = initial_res.total_tokens + repair_res.total_tokens

            try:
                parsed_repaired = _parse_and_validate_schema(repair_res.raw_output, response_schema)
                return LLMCallResult(
                    provider=repair_res.provider,
                    requested_model=model,
                    actual_model=repair_res.actual_model,
                    latency_ms=total_latency,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_comp,
                    total_tokens=total_tok,
                    raw_output=repair_res.raw_output,
                    parsed_result=parsed_repaired,
                    request_id=repair_res.request_id,
                    repair_attempted=True,
                    attempts=attempts,
                )
            except (json.JSONDecodeError, ValidationError, ValueError) as second_schema_err:
                raise LLMSchemaValidationError(
                    f"Schema validation failed after 1 same-model repair on "
                    f"{repair_res.provider}/{repair_res.actual_model}: {second_schema_err}",
                    error_classification="SCHEMA_VALIDATION_ERROR",
                    provider=repair_res.provider,
                    requested_model=model,
                    actual_model=repair_res.actual_model,
                    request_id=repair_res.request_id,
                    repair_attempted=True,
                    attempts=attempts,
                    latency_ms=total_latency,
                    raw_output=repair_res.raw_output,
                ) from second_schema_err


def generate_content_with_retry(
    client: Any = None,
    model: str = "gemini-3.8-flash",
    contents: Optional[Sequence[Union[LLMMessage, Dict[str, Any], str]]] = None,
    max_retries: int = 1,
    initial_delay: float = 0.5,
    *,
    system_prompt: Optional[str] = None,
    response_schema: Optional[Type[T]] = None,
    groq_client_factory: Optional[Callable[[], Any]] = None,
) -> LLMCallResult[T]:
    """Unified entrypoint replacing `gemini_client.generate_content_with_retry`.

    Returns a full `LLMCallResult[T]` (which also exposes `.text` for legacy callers).
    """
    gateway = LLMGateway(
        gemini_client=client,
        groq_client_factory=groq_client_factory,
    )
    return gateway.call(
        contents=contents,
        model=model,
        system_prompt=system_prompt,
        response_schema=response_schema,
    )
