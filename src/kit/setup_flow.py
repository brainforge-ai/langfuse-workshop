"""`kit setup` and `kit set-llm-key`: collect credentials, prove them, and say what comes next."""

from __future__ import annotations

import argparse
import getpass
from collections.abc import Callable

from kit import config, console, history, llm, preflight, state, tracing
from kit.errors import LF_TRACE_UNCONFIRMED
from kit.langfuse_api import Project, region_name
from kit.preflight import Services

Ask = Callable[[str], str]

# (slot, prompt label, typed hidden)
PROMPTS = (
    # Secret before public in each pair, the order Langfuse shows them on a new key.
    (config.LANGFUSE_SECRET_KEY, "Tracing secret key (sk-lf-...)", True),
    (config.LANGFUSE_PUBLIC_KEY, "Tracing public key (pk-lf-...)", False),
    (config.AGENT_SECRET_KEY, "Agent secret key (sk-lf-...)", True),
    (config.AGENT_PUBLIC_KEY, "Agent public key (pk-lf-...)", False),
    (config.LLM_KEY, "Workshop LLM key (sk-or-...)", True),
)

# Printed before the first prompt of each group, so the terminal walks the same steps as the README.
INTROS = {
    config.LANGFUSE_SECRET_KEY: "Tracing key: copy it from the screen Langfuse shows after you create the project.",
    config.AGENT_SECRET_KEY: (
        "Agent key: in Langfuse open Settings (bottom left) > API Keys, create a key with "
        "Developer permissions, and paste it here."
    ),
    config.LLM_KEY: "Workshop LLM key: open the 1Password link the presenters shared and copy the key.",
}

NEXT_COMMAND = "uv run kit tickets"


def prompt_values(existing: dict[str, str], ask: Ask, ask_secret: Ask) -> dict[str, str]:
    """Ask for each credential. Pressing Enter keeps the value already in `.env`, unless it is a placeholder."""
    values: dict[str, str] = {}
    for key, label, hidden in PROMPTS:
        if key in INTROS:
            console.say(f"\n{INTROS[key]}")
        current = existing.get(key, "")
        if config.is_placeholder(current):
            current = ""
        keep = f" [Enter keeps {console.mask(current)}]" if current else ""
        while True:
            value = config.clean((ask_secret if hidden else ask)(f"{label}{keep}: ")) or current
            if value:
                break
            console.say("  This one is needed. Paste it and press Enter.")
        console.say(f"  -> {console.mask(value)}")
        values[key] = value
    return values


def run_setup(*, ask: Ask = input, ask_secret: Ask = getpass.getpass, services: Services | None = None) -> int:
    services = services or Services()
    console.say("Paste each key and press Enter. Secret keys stay hidden while you paste.")
    existing = config.read_env()
    values = {**existing, **prompt_values(existing, ask, ask_secret)}

    preflight.check_prefixes(values)
    config.write_env(values)

    console.say("\nChecking the tracing key pair...")
    with console.spinner():
        host, project = preflight.find_project(values, services)
    state.update(host=host, project_id=project.id, project_name=project.name)
    console.say(f"  OK: project `{project.name}` on {host}")

    console.say("Checking the agent key pair...")
    with console.spinner():
        preflight.check_agent_project(host, project, values, services)
    console.say("  OK: same project")

    console.say("Checking the workshop LLM key...")
    with console.spinner():
        preflight.check_llm_key(values[config.LLM_KEY], services)
    console.say("  OK: the model answered")

    console.say("Sending a hello trace (confirming it can take up to 30 seconds)...")
    trace_id = services.send_hello()
    link = tracing.trace_url(trace_id)
    with console.spinner():
        confirmed = preflight.confirm_hello(host, values, trace_id, services)
    if confirmed:
        console.say(f"  OK: {link}")
    else:
        console.warn(
            f"[{LF_TRACE_UNCONFIRMED}] The hello trace was sent but has not shown up in Langfuse yet. "
            f"It may take a minute. Check it here: {link}"
        )

    history_line = load_history(host, project, values, services, ask)

    region = region_name(host)
    console.say("\nSetup is done.")
    console.say(f"  Region:  {region} ({host})" if region else f"  Host:    {host}")
    console.say(f"  Project: {project.name}")
    console.say(f"  {history_line}")
    console.say(f"\nNext, run: {NEXT_COMMAND}")
    return 0


def load_history(
    host: str,
    project: Project,
    values: dict[str, str],
    services: Services,
    ask: Ask,
    records: Callable[[], list] = history.records,
) -> str:
    """Load the recorded history once, after asking, and return the summary line about it."""
    api = services.api(host, values[config.LANGFUSE_PUBLIC_KEY], values[config.LANGFUSE_SECRET_KEY])
    with console.spinner():
        where = history.status(api)
    if where == history.LOADED:
        return "History: already loaded by an earlier setup. Nothing was sent again."
    if where == history.OTHER_RUN:
        err = history.already_loaded_error()
        console.error(err.code, err.message, err.fix)
        return "History: not loaded again (see the note above)."
    verb = "Finish loading" if where == history.PARTIAL else "Load"
    answer = ask(f"\n{verb} two weeks of workshop history into project `{project.name}`? [Y/n] ")
    if answer.strip().lower() in ("n", "no"):
        return "History: not loaded. Run `uv run kit setup` again when you want it."
    console.say("Loading history...")
    with console.spinner():
        report = history.load(api, records(), progress=lambda line: console.say(f"  {line}"))
    if report.scores_unsent:
        return "History: traces loaded, but some scores did not go through. Run `uv run kit setup` again to finish."
    note = f" {len(report.batches_uncertain)} batch(es) timed out and were skipped." if report.batches_uncertain else ""
    return (
        "History: loaded. Scores can take about 10 minutes to appear in Langfuse charts."
        + note
    )


def run_set_llm_key(*, ask_secret: Ask = getpass.getpass, services: Services | None = None) -> int:
    """Replace only the workshop LLM key, prove it, and name both places the key lives."""
    services = services or Services()
    key = config.clean(ask_secret("New workshop LLM key (sk-or-...): "))
    preflight.check_llm_prefix(key)
    console.say(f"  -> {console.mask(key)}")

    values = config.read_env()
    values[config.LLM_KEY] = key
    config.write_env(values)

    console.say("Checking the new key...")
    preflight.check_llm_key(key, services)
    console.say("  OK: the model answered")
    console.say(
        "\nThe key switch has two steps:\n"
        "  1. Done: the kit now uses the new key.\n"
        f"  2. In Langfuse, open Settings > LLM Connections, edit `{llm.CONNECTION_NAME}` and paste the same key."
    )
    return 0


def _setup(args: argparse.Namespace) -> int:
    return run_setup()


def _set_llm_key(args: argparse.Namespace) -> int:
    return run_set_llm_key()


def register(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "setup", help="Paste your keys, prove they work and send a hello trace."
    ).set_defaults(handler=_setup)
    sub.add_parser(
        "set-llm-key", help="Swap in a new workshop LLM key without re-running setup."
    ).set_defaults(handler=_set_llm_key)
