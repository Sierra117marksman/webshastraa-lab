import time
import logging
from typing import Any, List, Dict
from google import genai

logger = logging.getLogger(__name__)

def generate_content_with_retry(
    client: genai.Client,
    model: str = 'gemini-3.6-flash',
    contents: List[Dict[str, Any]] = None,
    max_retries: int = 3,
    initial_delay: float = 2.0
) -> Any:
    """
    Executes Gemini content generation with exponential backoff on 503/429/UNAVAILABLE errors.
    """
    delay = initial_delay
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents
            )
        except Exception as e:
            last_error = e
            err_msg = str(e)
            is_transient = any(code in err_msg for code in ['503', '429', 'UNAVAILABLE', 'ResourceExhausted', 'high demand'])
            if attempt < max_retries and is_transient:
                logger.warning(f"[Gemini Retry] Attempt {attempt} failed ({err_msg}). Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise e
    raise last_error
