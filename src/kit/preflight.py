"""Checks that prove each credential works, in the order setup runs them.

Prefix checks run first and need no network. Each failure names the slot at fault and what
to paste instead.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from kit import config, llm, tracing
from kit.errors import (
    LF_KEY_SWAPPED,
    LF_KEYPAIR,
    LF_NOT_A_LANGFUSE_KEY,
    LF_PROJECT_MISMATCH,
    LLM_NOT_AN_LLM_KEY,
    KitError,
)
from kit.langfuse_api import CLOUD_HOSTS, KeysRejected, LangfuseApi, Project

PUBLIC_PREFIX = "pk-lf-"
SECRET_PREFIX = "sk-lf-"
LLM_PREFIX = llm.KEY_PREFIX

# What each `.env` slot is called on screen.
SLOT_NAMES = {
    config.LANGFUSE_PUBLIC_KEY: "tracing public key",
    config.LANGFUSE_SECRET_KEY: "tracing secret key",
    config.AGENT_PUBLIC_KEY: "agent public key",
    config.AGENT_SECRET_KEY: "agent secret key",
    config.LLM_KEY: "workshop LLM key",
}

# Langfuse key pairs, tracing first: (public slot, secret slot).
LANGFUSE_PAIRS = (
    (config.LANGFUSE_PUBLIC_KEY, config.LANGFUSE_SECRET_KEY),
    (config.AGENT_PUBLIC_KEY, config.AGENT_SECRET_KEY),
)

RERUN = "then run `uv run kit setup` again"
KEYS_PAGE = "Settings > API Keys in your langfuse-workshop project"

# Ingestion is not instant; wait this long before the one read that confirms the hello trace.
HELLO_CONFIRM_DELAY = 3.0
# Langfuse can take about 20 seconds to make a new trace readable, so check for up to 30.
HELLO_CONFIRM_TRIES = 10
HELLO_NAME = "kit-hello"


def slot(key: str) -> str:
    return f"{SLOT_NAMES[key]} ({key})"


def send_hello_trace(span_exporter: Any = None) -> str:
    """Send one root observation through the SDK and return its trace ID."""
    langfuse = tracing.client(span_exporter=span_exporter)
    hello = langfuse.start_observation(
        name=HELLO_NAME,
        input={"message": "hello from the workshop kit"},
        output={"message": "setup can reach this project"},
    )
    hello.end()
    langfuse.flush()
    return hello.trace_id


@dataclass
class Services:
    """Everything preflight reaches outside the process, so tests can stand in for it."""

    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    llm_client: Callable[[str], Any] = field(default=llm.client)
    send_hello: Callable[[], str] = field(default=send_hello_trace)

    def api(self, host: str, public_key: str, secret_key: str) -> LangfuseApi:
        return LangfuseApi(host, public_key, secret_key, transport=self.transport, sleep=self.sleep)


# --- Offline prefix checks --------------------------------------------------------------------


def check_prefixes(values: dict[str, str]) -> None:
    for public_key, secret_key in LANGFUSE_PAIRS:
        _check_one(public_key, values.get(public_key, ""), want=PUBLIC_PREFIX, other=SECRET_PREFIX)
        _check_one(secret_key, values.get(secret_key, ""), want=SECRET_PREFIX, other=PUBLIC_PREFIX)
    check_llm_prefix(values.get(config.LLM_KEY, ""))


def _check_one(key: str, value: str, *, want: str, other: str) -> None:
    if value.startswith(want):
        return
    if value.startswith(other):
        raise KitError(
            LF_KEY_SWAPPED,
            f"The {slot(key)} holds a key starting `{other}`, which belongs in the other slot of the pair.",
            f"Paste the key starting `{want}` as the {SLOT_NAMES[key]}, {RERUN}.",
        )
    hint = " That is the workshop LLM key." if value.startswith(LLM_PREFIX) else ""
    raise KitError(
        LF_NOT_A_LANGFUSE_KEY,
        f"The {slot(key)} is not a Langfuse key.{hint}",
        f"Paste the Langfuse key starting `{want}` from {KEYS_PAGE}, {RERUN}.",
    )


def check_llm_prefix(value: str) -> None:
    if value.startswith(LLM_PREFIX):
        return
    hint = " That is a Langfuse key." if value.startswith((SECRET_PREFIX, PUBLIC_PREFIX)) else ""
    raise KitError(
        LLM_NOT_AN_LLM_KEY,
        f"The {slot(config.LLM_KEY)} is not an OpenRouter key.{hint}",
        f"Paste the workshop LLM key from the 1Password link. It starts with `{LLM_PREFIX}`.",
    )


# --- Network checks ---------------------------------------------------------------------------


def find_project(values: dict[str, str], services: Services) -> tuple[str, Project]:
    """The host that accepts the tracing pair, and the project it belongs to.

    A `LANGFUSE_BASE_URL` already in `.env` is used as is. Otherwise each Cloud region is
    tried in turn and the first that accepts the pair wins.
    """
    public, secret = values[config.LANGFUSE_PUBLIC_KEY], values[config.LANGFUSE_SECRET_KEY]
    preset = values.get(config.BASE_URL)
    hosts = [preset.rstrip("/")] if preset else [url for _, url in CLOUD_HOSTS]
    for host in hosts:
        try:
            return host, services.api(host, public, secret).project()
        except KeysRejected:
            continue
    where = f"the Langfuse host {hosts[0]}" if preset else "any Langfuse Cloud region"
    raise KitError(
        LF_KEYPAIR,
        f"The tracing key pair ({config.LANGFUSE_PUBLIC_KEY}, {config.LANGFUSE_SECRET_KEY}) "
        f"was not accepted by {where}.",
        f"Copy both tracing keys again from {KEYS_PAGE}, {RERUN}.",
    )


def check_agent_project(host: str, project: Project, values: dict[str, str], services: Services) -> None:
    """The agent pair must belong to the same project as the tracing pair."""
    names = f"{config.AGENT_PUBLIC_KEY}, {config.AGENT_SECRET_KEY}"
    api = services.api(host, values[config.AGENT_PUBLIC_KEY], values[config.AGENT_SECRET_KEY])
    try:
        agent_project = api.project()
    except KeysRejected:
        raise KitError(
            LF_KEYPAIR,
            f"The agent key pair ({names}) was not accepted by {host}.",
            f"Create a second key pair in {KEYS_PAGE}, paste it as the agent keys, {RERUN}.",
        ) from None
    if agent_project.id != project.id:
        raise KitError(
            LF_PROJECT_MISMATCH,
            f"The agent key pair ({names}) belongs to project `{agent_project.name}`, "
            f"not `{project.name}` like the tracing pair.",
            f"Create the agent key pair in the `{project.name}` project, paste it as the agent keys, {RERUN}.",
        )


def check_llm_key(key: str, services: Services) -> None:
    """One minimal model call. The llm module turns any failure into its own code."""
    llm.create(
        services.llm_client(key),
        max_tokens=5,
        messages=[{"role": "user", "content": "Reply with OK."}],
    )


def confirm_hello(host: str, values: dict[str, str], trace_id: str, services: Services) -> bool:
    """Read the trace by ID a few times while Langfuse catches up. A failure means only that it was not confirmed."""
    api = services.api(host, values[config.LANGFUSE_PUBLIC_KEY], values[config.LANGFUSE_SECRET_KEY])
    for _ in range(HELLO_CONFIRM_TRIES):
        services.sleep(HELLO_CONFIRM_DELAY)
        try:
            if api.trace_has_observations(trace_id):
                return True
        except (KitError, KeysRejected, httpx.HTTPError):
            pass
    return False
