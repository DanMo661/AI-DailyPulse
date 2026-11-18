"""Shared OpenAI-compatible LLM client with retry + JSON reply parsing.

Every LLM call in the pipeline goes through chat(): transient network/5xx
errors are retried with backoff so a single blip doesn't drop an article.
"""

import json
import re
import time

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_MAX_RETRIES = 2
# a retry_after beyond this = provider capacity gone for hours; don't stall the run
_MAX_RETRY_AFTER = 90

_client = None


def _get_client() -> OpenAI:
    """Lazy client: created on first LLM call, so collect-only runs work without a key."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def _retry_wait(attempt: int, err: Exception) -> int | None:
    """Seconds to wait before the next attempt, or None to give up.

    Rate-limit bodies (e.g. OrcaRouter 429) carry retry_after_seconds: honor
    it when it's short enough to stay inside the run window; a huge value
    means the provider's capacity is out for hours — retrying is pointless.
    """
    m = re.search(r"retry_after_seconds['\"]?[:\s]+(\d+)", str(err))
    if m:
        wait = int(m.group(1))
        return wait if wait <= _MAX_RETRY_AFTER else None
    return 3 * (2 ** attempt)


def chat(system: str, user: str, temperature: float = 0.3, max_tokens: int = 2000, json_mode: bool = False) -> str:
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = _get_client().chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                wait = _retry_wait(attempt, e)
                if wait is None:
                    break  # provider out of capacity for hours — fail fast
                print(f"[llm] attempt {attempt + 1} failed ({e}), retrying in {wait}s")
                time.sleep(wait)
    raise last_err


def parse_json(text: str) -> dict:
    """Parse a JSON object out of an LLM reply (with fence fallback)."""
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
