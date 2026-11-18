"""The Langfuse client the app traces with, built from `.env` and the saved host."""

from __future__ import annotations

from langfuse import Langfuse

from kit import config, state
from kit.errors import not_set_up

APP_VERSION = "1.3.0"
ROOT_NAME = "sql-agent"


def host() -> str:
    env = config.read_env()
    saved = state.load().get("host")
    value = env.get(config.BASE_URL) or saved
    if not value:
        raise not_set_up()
    return value.rstrip("/")


def client(span_exporter=None) -> Langfuse:
    """A Langfuse client using the tracing key pair. `span_exporter` captures spans locally."""
    env = config.read_env()
    public, secret = env.get(config.LANGFUSE_PUBLIC_KEY), env.get(config.LANGFUSE_SECRET_KEY)
    if not public or not secret:
        raise not_set_up()
    return Langfuse(
        public_key=public,
        secret_key=secret,
        base_url=host(),
        release=APP_VERSION,
        span_exporter=span_exporter,
    )


def trace_url(trace_id: str) -> str:
    project_id = state.load().get("project_id", "")
    return f"{host()}/project/{project_id}/traces/{trace_id}"
