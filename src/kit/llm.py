"""The workshop LLM: one model, one key from `.env`, and plain messages for every failure."""

from __future__ import annotations

from typing import Any

import anthropic

from kit import config
from kit.errors import LLM_KEY, LLM_MODEL, LLM_RATE, KitError, connection_error, not_set_up

# The one place the model is named. The Langfuse LLM connection uses the same model.
MODEL = "claude-haiku-5-5"
MAX_OUTPUT_TOKENS = 1024

KEY_SWITCH_FIX = (
    "Switch to the reserve key in two places:\n"
    "  1. Run `uv run kit set-llm-key` and paste the reserve key the presenters share.\n"
    "  2. In Langfuse, open Settings > LLM Connections, edit `anthropic` and paste the same key."
)

# Phrases a provider uses when a key is out of credit or past its spend limit.
_KEY_LEVEL_HINTS = ("credit", "billing", "spend", "limit", "quota", "disabled", "revoked")


def client(api_key: str | None = None) -> anthropic.Anthropic:
    key = api_key or config.read_env().get(config.LLM_KEY)
    if not key:
        raise not_set_up()
    return anthropic.Anthropic(api_key=key, max_retries=4, timeout=60.0)


def create(llm: anthropic.Anthropic, **request: Any) -> Any:
    """Send one request with the kit's fixed settings and translate failures."""
    request.setdefault("model", MODEL)
    request.setdefault("max_tokens", MAX_OUTPUT_TOKENS)
    request.setdefault("thinking", {"type": "disabled"})
    try:
        return llm.messages.create(**request)
    except anthropic.APIStatusError as exc:
        raise translate(exc) from exc
    except anthropic.APIConnectionError as exc:
        raise connection_error(exc) from exc


def translate(exc: anthropic.APIStatusError) -> KitError:
    status = exc.status_code
    text = str(getattr(exc, "message", exc)).lower()
    if status == 429 or status >= 500:
        return KitError(
            LLM_RATE,
            "The workshop LLM key is busy right now.",
            "Wait 30 seconds and run the same command again.",
        )
    if status == 404 or (status == 400 and "model" in text and "not" in text):
        return KitError(
            LLM_MODEL,
            f"The model `{MODEL}` is not available to this key.",
            "Tell a presenter. The kit may need the fallback model.",
        )
    if status in (401, 402, 403) or (status == 400 and any(h in text for h in _KEY_LEVEL_HINTS)):
        return KitError(LLM_KEY, "The workshop LLM key was rejected. It may be capped or revoked.", KEY_SWITCH_FIX)
    return KitError(
        LLM_MODEL,
        f"The model request failed ({status}).",
        "Run the command again. If it keeps failing, tell a presenter.",
    )
