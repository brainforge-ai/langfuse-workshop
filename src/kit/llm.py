"""The workshop LLM: one model on OpenRouter, one key from `.env`, and plain messages for every failure."""

from __future__ import annotations

from typing import Any

import openai

from kit import config
from kit.errors import LLM_KEY, LLM_MODEL, LLM_RATE, KitError, connection_error, not_set_up

# The one place the model is named. The Langfuse LLM connection uses the same model.
BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "deepseek/deepseek-v4.1-flash-1017"
MAX_OUTPUT_TOKENS = 1024
KEY_PREFIX = "sk-or-"
# The name attendees give the LLM connection in Langfuse.
CONNECTION_NAME = "openrouter"

# The model reasons by default. The agent and the key check turn that off so answers come back fast.
# Judges keep the default, the same way Langfuse-hosted judges run, so local scores match hosted ones.
NO_REASONING = {"reasoning": {"effort": "none"}}

KEY_SWITCH_FIX = (
    "Switch to the reserve key in two places:\n"
    "  1. Run `uv run kit set-llm-key` and paste the reserve key the presenters share.\n"
    f"  2. In Langfuse, open Settings > LLM Connections, edit `{CONNECTION_NAME}` and paste the same key."
)

# Phrases OpenRouter uses when a key is out of credit or past its limit.
_KEY_LEVEL_HINTS = ("credit", "billing", "key limit", "limit exceeded", "quota", "disabled", "revoked")
# Phrases it uses when the key may not call this model or no provider can serve it.
_MODEL_HINTS = ("model", "guardrail", "allowlist", "allowed", "endpoint")


def client(api_key: str | None = None) -> openai.OpenAI:
    key = api_key or config.read_env().get(config.LLM_KEY)
    if not key:
        raise not_set_up()
    return openai.OpenAI(
        api_key=key,
        base_url=BASE_URL,
        max_retries=4,
        timeout=60.0,
        default_headers={"X-Title": "Langfuse workshop kit"},
    )


def create(llm: Any, *, reasoning: bool = False, **request: Any) -> Any:
    """Send one chat request with the kit's fixed settings and translate failures.

    `reasoning=True` leaves the model's default reasoning on instead of turning it off.
    """
    request.setdefault("model", MODEL)
    request.setdefault("max_tokens", MAX_OUTPUT_TOKENS)
    if not reasoning:
        request["extra_body"] = {**NO_REASONING, **(request.get("extra_body") or {})}
    try:
        response = llm.chat.completions.create(**request)
    except openai.APIStatusError as exc:
        raise translate(exc) from exc
    except openai.APIConnectionError as exc:
        raise connection_error(exc) from exc
    # OpenRouter can answer 200 with no usable choice when the upstream provider fails.
    choices = getattr(response, "choices", None) or []
    if not choices or getattr(choices[0], "finish_reason", None) == "error":
        raise _busy()
    return response


def _busy() -> KitError:
    return KitError(
        LLM_RATE,
        "The workshop LLM key is busy right now.",
        "Wait 30 seconds and run the same command again.",
    )


def translate(exc: openai.APIStatusError) -> KitError:
    status = exc.status_code
    text = f"{getattr(exc, 'message', '')} {getattr(exc, 'body', '')}".lower()
    if status in (408, 429) or status >= 500:
        return _busy()
    key_level = any(h in text for h in _KEY_LEVEL_HINTS)
    if status == 404 or (status in (400, 403) and not key_level and any(h in text for h in _MODEL_HINTS)):
        return KitError(
            LLM_MODEL,
            f"The model `{MODEL}` is not available to this key.",
            "Tell a presenter.",
        )
    if status in (401, 402, 403) or (status == 400 and key_level):
        return KitError(LLM_KEY, "The workshop LLM key was rejected. It may be capped or revoked.", KEY_SWITCH_FIX)
    return KitError(
        LLM_MODEL,
        f"The model request failed ({status}).",
        "Run the command again. If it keeps failing, tell a presenter.",
    )
