"""The `kit` command. Every subcommand runs inside one error boundary."""

from __future__ import annotations

import argparse
import datetime as dt
import traceback
from collections.abc import Callable

from kit import config, console, evaluators, llm, mcp, setup_flow, state, tickets, tracing
from kit.agent import agent
from kit.errors import KIT_UNEXPECTED, LF_KEYPAIR, KitError, not_set_up
from kit.langfuse_api import KeysRejected, LangfuseApi

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


def _ask(args: argparse.Namespace) -> int:
    _send([(args.question, ASK_CUSTOMER, None)])
    return 0


def _ticket(args: argparse.Namespace) -> int:
    ticket = tickets.get(args.number)
    if ticket is None:
        console.say(f"There is no ticket {args.number}. Tickets run from 1 to {len(tickets.load())}.")
        return 1
    _send([(ticket.question, ticket.customer, ticket)])
    return 0


def _tickets(_: argparse.Namespace) -> int:
    _send([(t.question, t.customer, t) for t in tickets.load()])
    return 0


def _send(jobs: list[tuple[str, str, tickets.Ticket | None]]) -> None:
    """Run each question through the agent, printing the answer and its trace link."""
    langfuse = tracing.client()
    llm_client = llm.client()
    try:
        for question, customer, ticket in jobs:
            console.say()
            if ticket is not None:
                console.say(f"--- Ticket {ticket.id} from {ticket.customer}")
                console.say(ticket.complaint)
            console.say(f"Q: {question}")
            result = agent.run(question, langfuse=langfuse, llm_client=llm_client, customer=customer)
            console.say(f"A: {result.answer}")
            console.say(f"Trace: {tracing.trace_url(result.trace_id)}")
    finally:
        langfuse.flush()


ASK_CUSTOMER = "workshop-attendee"


def _register_agent_commands(sub: argparse._SubParsersAction) -> None:
    ask = sub.add_parser("ask", help="Ask the agent your own question.")
    ask.add_argument("question", help="The question, in quotes.")
    ask.set_defaults(handler=_ask)

    one = sub.add_parser("ticket", help="Send one customer ticket, for example `kit ticket 3`.")
    one.add_argument("number", type=int, help="Ticket number, 1 to 10.")
    one.set_defaults(handler=_ticket)

    every = sub.add_parser("tickets", help="Send all ten customer tickets.")
    every.set_defaults(handler=_tickets)


def _install_evaluators(_: argparse.Namespace) -> int:
    values = config.read_env()
    public, secret = values.get(config.AGENT_PUBLIC_KEY), values.get(config.AGENT_SECRET_KEY)
    if not public or not secret:
        raise not_set_up()
    api = LangfuseApi(tracing.host(), public, secret)
    console.say(f"Installing workshop evaluators into project `{state.load().get('project_name', '?')}`...")
    try:
        report = evaluators.install(api)
    except KeysRejected as exc:
        raise KitError(
            LF_KEYPAIR,
            "Langfuse rejected the agent key pair (LANGFUSE_AGENT_PUBLIC_KEY and LANGFUSE_AGENT_SECRET_KEY).",
            "Run `uv run kit setup` and paste a working agent key pair.",
        ) from exc
    evaluators.print_report(report)
    return 1 if report.name_taken else 0


def _register_evaluator_command(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "install-evaluators", help="Install the four workshop evaluators into your Langfuse project."
    ).set_defaults(handler=_install_evaluators)
    sub.add_parser(
        "mcp", help="Print the settings that connect your coding agent to Langfuse's MCP server."
    ).set_defaults(handler=lambda _: mcp.run())


# Each entry adds subcommands and sets their handler with set_defaults(handler=...).
_COMMANDS: list[Callable[[argparse._SubParsersAction], None]] = [
    setup_flow.register,
    _register_agent_commands,
    _register_evaluator_command,
]


def main(argv: list[str] | None = None) -> int:
    console.configure()
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return guarded(handler, args)
