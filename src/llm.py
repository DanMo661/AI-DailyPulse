"""Shared OpenAI-compatible LLM client with retry + JSON reply parsing.

Every LLM call in the pipeline goes through chat(): transient network/5xx
errors are retried with backoff so a single blip doesn't drop an article.
"""

import json
import time

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_MAX_RETRIES = 2

_client = None


def _get_client() -> OpenAI:
    """Lazy client: created on first LLM call, so collect-only runs work without a key."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


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
                wait = 3 * (2 ** attempt)
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
