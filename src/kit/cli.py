"""The `kit` command. Every subcommand runs inside one error boundary."""

from __future__ import annotations

import argparse
import datetime as dt
import traceback
from collections.abc import Callable

from kit import config, console
from kit.errors import KIT_UNEXPECTED, KitError

Handler = Callable[[argparse.Namespace], int | None]


def guarded(handler: Handler, args: argparse.Namespace) -> int:
    """Run a command. Known failures print a code and a fix; nothing prints a traceback."""
    try:
        return handler(args) or 0
    except KitError as exc:
        console.error(exc.code, exc.message, exc.fix)
        return 1
    except KeyboardInterrupt:
        console.say("\nStopped.")
        return 130
    except Exception:
        log = _write_log(traceback.format_exc())
        console.error(
            KIT_UNEXPECTED,
            "Something went wrong inside the kit.",
            f"Details were saved to {log}. Show that file to a presenter.",
        )
        return 1


def _write_log(details: str) -> str:
    try:
        path = config.state_dir() / "kit.log"
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"--- {stamp}\n{details}\n")
        return str(path)
    except OSError:
        return "(the log file could not be written)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kit",
        description="Langfuse workshop kit. Start with `uv run kit setup`.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for register in _COMMANDS:
        register(sub)
    return parser


# Each entry adds one subcommand and sets its handler with set_defaults(handler=...).
_COMMANDS: list[Callable[[argparse._SubParsersAction], None]] = []


def main(argv: list[str] | None = None) -> int:
    console.configure()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return guarded(handler, args)
