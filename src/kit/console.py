"""Terminal output that never crashes on a console that cannot print a character."""

from __future__ import annotations

import sys

KEY_PREFIXES = ("pk-lf-", "sk-lf-", "sk-ant-")


def configure() -> None:
    """Replace characters the console cannot encode instead of raising."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def say(text: str = "") -> None:
    print(text, flush=True)


def warn(text: str) -> None:
    print(f"Warning: {text}", file=sys.stderr, flush=True)


def error(code: str, message: str, fix: str) -> None:
    print(f"\n[{code}] {message}\nFix: {fix}", file=sys.stderr, flush=True)


def mask(key: str) -> str:
    """Show a key's prefix and last four characters and nothing else."""
    if not key:
        return "(empty)"
    prefix = next((p for p in KEY_PREFIXES if key.startswith(p)), key[:3])
    rest = key[len(prefix) :]
    if len(rest) <= 4:
        return f"{prefix}..."
    return f"{prefix}...{rest[-4:]}"
