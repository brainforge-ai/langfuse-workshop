"""Local configuration: the `.env` file with credentials and the `.kit/` state folder.

Values are read fresh on every command, so editing `.env` takes effect at once.
"""

from __future__ import annotations

import os
from pathlib import Path

LANGFUSE_PUBLIC_KEY = "LANGFUSE_PUBLIC_KEY"
LANGFUSE_SECRET_KEY = "LANGFUSE_SECRET_KEY"
AGENT_PUBLIC_KEY = "LANGFUSE_AGENT_PUBLIC_KEY"
AGENT_SECRET_KEY = "LANGFUSE_AGENT_SECRET_KEY"
LLM_KEY = "WORKSHOP_LLM_KEY"
BASE_URL = "LANGFUSE_BASE_URL"

ENV_KEYS = (
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    AGENT_PUBLIC_KEY,
    AGENT_SECRET_KEY,
    LLM_KEY,
    BASE_URL,
)


def home() -> Path:
    """The folder that holds `.env` and `.kit/`: the repo root the attendee runs from."""
    override = os.environ.get("KIT_HOME")
    return Path(override) if override else Path.cwd()


def env_path() -> Path:
    return home() / ".env"


def state_dir() -> Path:
    path = home() / ".kit"
    path.mkdir(exist_ok=True)
    return path


# The values `.env.example` ships with. A `.env` copied from it still holds these until filled in.
PLACEHOLDERS = frozenset({"pk-lf-...", "sk-lf-...", "sk-or-..."})


def is_placeholder(value: str) -> bool:
    return value in PLACEHOLDERS


def clean(value: str) -> str:
    """Strip whitespace and one pair of surrounding quotes from a pasted value."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or env_path()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    # utf-8-sig drops the byte-order mark Windows editors may add.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        values[key.strip()] = clean(value)
    return values


def write_env(values: dict[str, str], path: Path | None = None) -> None:
    """Write known keys in a fixed order, then any others the file already held."""
    path = path or env_path()
    ordered = [k for k in ENV_KEYS if values.get(k)]
    ordered += [k for k in values if k not in ENV_KEYS and values[k]]
    text = "".join(f"{key}={clean(values[key])}\n" for key in ordered)
    path.write_text(text, encoding="utf-8")
