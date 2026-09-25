import os
import time
import logging
from typing import Any, List, Dict, Optional
from google import genai

logger = logging.getLogger(__name__)

FALLBACK_MODELS = ['gemini-3.5-flash', 'gemini-flash-latest', 'gemini-3.5-flash-lite', 'gemini-3.7-flash', 'gemini-3.6-flash']
GROQ_MODELS = ['openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'openai/gpt-oss-20b']

class LLMResponse:
    def __init__(self, text: str):
        self.text = text

def _try_groq_inference(contents: List[Dict[str, Any]]) -> Optional[LLMResponse]:
    groq_api_key = os.getenv('GROQ_API_KEY')
    if not groq_api_key:
        return None

    try:
        from groq import Groq
        groq_client = Groq(api_key=groq_api_key)

        # Convert Gemini contents format to OpenAI/Groq message list
        messages = []
        for turn in contents:
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
                output = res.choices[0].message.content or ''
                elapsed = time.time() - t0
                logger.info(f"[Groq LPU] Finished in {elapsed:.2f}s via {model} (Length: {len(output)})")
                return LLMResponse(output)
            except Exception as ge:
                logger.warning(f"[Groq Error] Model {model} failed ({str(ge)[:90]}). Trying next...")
                continue
    except Exception as e:
        logger.warning(f"[Groq Init Error] {e}")

    return None

def generate_content_with_retry(
    client: genai.Client,
    model: str = 'gemini-3.5-flash',
    contents: List[Dict[str, Any]] = None,
    max_retries: int = 2,
    initial_delay: float = 1.5
) -> Any:
    """
    Executes LLM content generation with multi-provider failover:
    1. Primary: Groq LPU (Ultra-fast, high request limits)
    2. Fallback: Google Gemini cascade across 5 production models
    """
    # 1. Attempt Groq first if key is present
    groq_res = _try_groq_inference(contents)
    if groq_res is not None and groq_res.text:
        return groq_res

    # 2. Fallback to Gemini Cascade
    logger.info("[LLM Engine] Running via Google Gemini cascade...")
    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error = None

    for current_model in models_to_try:
        delay = initial_delay
        for attempt in range(1, max_retries + 1):
            try:
                return client.models.generate_content(
                    model=current_model,
                    contents=contents
                )
            except Exception as e:
                last_error = e
                err_msg = str(e)
                is_quota = '429' in err_msg or 'RESOURCE_EXHAUSTED' in err_msg or 'quota' in err_msg.lower()
                is_transient = any(code in err_msg for code in ['503', 'UNAVAILABLE', 'high demand'])

                if is_quota:
                    logger.warning(f"[Gemini Quota Exceeded] Model {current_model} hit 429. Cascading to next fallback model...")
                    break  # Break inner loop to try next model immediately without waiting!

                if attempt < max_retries and is_transient:
                    logger.warning(f"[Gemini Transient] {current_model} attempt {attempt} failed ({err_msg[:80]}). Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    break

    raise last_error

