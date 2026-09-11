import os
import time
import logging
from typing import Any, List, Dict
from google import genai

logger = logging.getLogger(__name__)

FALLBACK_MODELS = ['gemini-3.5-flash', 'gemini-flash-latest', 'gemini-3.5-flash-lite', 'gemini-3.7-flash', 'gemini-3.6-flash']

def generate_content_with_retry(
    client: genai.Client,
    model: str = 'gemini-3.5-flash',
    contents: List[Dict[str, Any]] = None,
    max_retries: int = 2,
    initial_delay: float = 1.5
) -> Any:
    """
    Executes Gemini content generation with multi-model failover and backoff.
    If a model hits 429 RESOURCE_EXHAUSTED, it immediately cascades to alternative high-quota models.
    """
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
