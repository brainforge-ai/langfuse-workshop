"""Terminal output that never crashes on a console that cannot print a character."""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO

KEY_PREFIXES = ("pk-lf-", "sk-lf-", "sk-or-v1-", "sk-or-")

# Plain ASCII so cmd and PowerShell draw it too.
SPINNER_FRAMES = "|/-\\"
SPINNER_INTERVAL = 0.12

# Held while the spinner draws and while a message prints, so the two never interleave.
_output_lock = threading.RLock()
# The stream the spinner has drawn on and not yet erased, if any.
_spinner_drawn_on: TextIO | None = None


def configure() -> None:
    """Replace characters the console cannot encode instead of raising."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def say(text: str = "") -> None:
    with _output_lock:
        _erase_spinner()
        print(text, flush=True)


def warn(text: str) -> None:
    with _output_lock:
        _erase_spinner()
        print(f"Warning: {text}", file=sys.stderr, flush=True)


def error(code: str, message: str, fix: str) -> None:
    with _output_lock:
        _erase_spinner()
        print(f"\n[{code}] {message}\nFix: {fix}", file=sys.stderr, flush=True)


def _is_terminal(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def _erase_spinner() -> None:
    """Blank the spinner's line and return to its start. Call with `_output_lock` held."""
    global _spinner_drawn_on
    stream, _spinner_drawn_on = _spinner_drawn_on, None
    if stream is not None:
        try:
            stream.write("\r   \r")
            stream.flush()
        except (OSError, ValueError):
            pass


@contextmanager
def spinner(stream: TextIO | None = None, interval: float = SPINNER_INTERVAL) -> Iterator[None]:
    """Show a small spinner while a slow step runs, on a terminal only.

    Messages printed with `say`, `warn` or `error` meanwhile erase it first, and it is
    erased when the step ends or raises. When output is not a terminal it does nothing.
    """
    global _spinner_drawn_on
    if stream is None:
        stream = sys.stdout
    if not _is_terminal(stream):
        yield
        return
    stop = threading.Event()

    def spin() -> None:
        global _spinner_drawn_on
        frame = 0
        while not stop.wait(interval):
            with _output_lock:
                if stop.is_set():
                    return
                try:
                    stream.write(f"\r  {SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]}")
                    stream.flush()
                except (OSError, ValueError):
                    return
                _spinner_drawn_on = stream
            frame += 1

    thread = threading.Thread(target=spin, name="kit-spinner", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
        with _output_lock:
            _erase_spinner()


def mask(key: str) -> str:
    """Show a key's prefix and last four characters and nothing else."""
    if not key:
        return "(empty)"
    prefix = next((p for p in KEY_PREFIXES if key.startswith(p)), key[:3])
    rest = key[len(prefix) :]
    if len(rest) <= 4:
        return f"{prefix}..."
    return f"{prefix}...{rest[-4:]}"
