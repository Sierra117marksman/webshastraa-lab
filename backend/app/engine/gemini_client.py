import os
import time
import base64
import logging
from typing import Any, List, Dict, Optional
from google import genai

logger = logging.getLogger(__name__)

# Distinct Gemini 3.x models with independent quota buckets (excludes gemini-flash-latest alias which maps back to 3.8)
FALLBACK_MODELS = [
    'gemini-3.8-flash',
    'gemini-3.7-flash',
    'gemini-3.6-flash',
    'gemini-3.5-flash-lite',
    'gemini-3.1-flash-lite'
]

GROQ_MODELS = [
    'openai/gpt-oss-120b',
    'qwen/qwen3.8-27b',
    'openai/gpt-oss-20b'
]

# Track models that recently hit 429 or 503 so multi-step tasks skip exhausted models immediately
_MODEL_COOLDOWN_UNTIL: Dict[str, float] = {}


def get_groq_api_key() -> str:
    return (os.getenv('GROQ_API_KEY') or '').strip()


class LLMResponse:
    def __init__(self, text: str):
        self.text = text


def _try_groq_inference(contents: List[Dict[str, Any]]) -> Optional[LLMResponse]:
    groq_api_key = get_groq_api_key()
    if not groq_api_key:
        return None

    try:
        from groq import Groq
        groq_client = Groq(api_key=groq_api_key)

        # Convert Gemini contents format to OpenAI/Groq message list
        messages = []
        for turn in contents or []:
            role = 'assistant' if turn.get('role') == 'model' else 'user'
            text = ''
            for part in turn.get('parts', []):
                text += part.get('text', '')
            if text:
                messages.append({'role': role, 'content': text})

        if not messages:
            return None

        for model in GROQ_MODELS:
            try:
                t0 = time.time()
                res = groq_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2
                )
                output = (res.choices[0].message.content or '').strip()
                if not output:
                    logger.warning(f"[Groq Empty] Model {model} returned empty content. Trying next...")
                    continue
                elapsed = time.time() - t0
                logger.info(f"[Groq LPU] Fallback inference finished in {elapsed:.2f}s via {model} (Length: {len(output)})")
                return LLMResponse(output)
            except Exception as ge:
                logger.warning(f"[Groq Error] Model {model} failed ({str(ge)[:90]}). Trying next...")
                continue
    except Exception as e:
        logger.warning(f"[Groq Init Error] {e}")

    return None


def generate_content_with_retry(
    client: genai.Client,
    model: str = 'gemini-3.8-flash',
    contents: List[Dict[str, Any]] = None,
    max_retries: int = 2,
    initial_delay: float = 1.0
) -> Any:
    """
    Executes LLM content generation with multi-provider failover and cooldown memory:
    1. Primary: Google Gemini 3.8 Flash -> 3.7 Flash -> 3.6 Flash -> 3.5 Flash Lite -> 3.1 Flash Lite
    2. Fallback: Groq LPU engine (openai/gpt-oss-120b -> qwen/qwen3.8-27b -> openai/gpt-oss-20b)
    """
    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error = None
    now = time.time()

    # 1. Primary: Attempt Google Gemini cascade, skipping models currently in quota cooldown
    for current_model in models_to_try:
        cooldown_until = _MODEL_COOLDOWN_UNTIL.get(current_model, 0.0)
        if now < cooldown_until:
            logger.info(f"[Gemini Cooldown] Skipping {current_model} (in quota cooldown for {int(cooldown_until - now)}s)")
            continue

        delay = initial_delay
        for attempt in range(1, max_retries + 1):
            try:
                res = client.models.generate_content(
                    model=current_model,
                    contents=contents
                )
                if res and getattr(res, 'text', None):
                    return res
            except Exception as e:
                last_error = e
                err_msg = str(e)
                is_quota = '429' in err_msg or 'RESOURCE_EXHAUSTED' in err_msg or 'quota' in err_msg.lower()
                is_daily_quota = 'PerDay' in err_msg or 'free_tier_requests' in err_msg
                is_transient = any(code in err_msg for code in ['503', 'UNAVAILABLE', 'high demand'])

                if is_quota:
                    # Cache cooldown so Step 2 & Step 3 don't hammer an exhausted model
                    cooldown_secs = 600.0 if is_daily_quota else 45.0
                    _MODEL_COOLDOWN_UNTIL[current_model] = time.time() + cooldown_secs
                    logger.warning(
                        f"[Gemini Quota Exceeded] Model {current_model} hit 429 (cooldown {int(cooldown_secs)}s). Cascading to next model..."
                    )
                    break

                if is_transient:
                    _MODEL_COOLDOWN_UNTIL[current_model] = time.time() + 25.0
                    if attempt < max_retries:
                        logger.warning(f"[Gemini Transient] {current_model} attempt {attempt} hit 503. Retrying in {delay}s...")
                        time.sleep(delay)
                        delay *= 1.5
                    else:
                        break
                else:
                    break

    # 2. Fallback: If Gemini cascade failed or exhausted quota, switch to Groq LPU
    logger.warning(f"[LLM Engine] Gemini models exhausted/failed ({last_error}). Falling back to Groq LPU...")
    groq_res = _try_groq_inference(contents)
    if groq_res is not None and groq_res.text:
        logger.info("[LLM Engine] Successfully recovered via Groq LPU fallback.")
        return groq_res

    # If both Gemini and Groq fail, raise last error
    if last_error:
        raise last_error
    raise RuntimeError("All Gemini and Groq fallback models failed to generate a response.")
