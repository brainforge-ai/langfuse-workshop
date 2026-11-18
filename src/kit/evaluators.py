"""`kit install-evaluators`: create the workshop's four judge evaluators and their rules.

It creates only what is missing and never modifies or deletes anything. It treats an
evaluator as its own only when the name is one of its four and the description
carries the kit's marker, so the attendee's hand-built evaluator is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kit import console, judges, llm, tracing
from kit.errors import EVAL_NAME_TAKEN, EVAL_NO_CONNECTION, KitError

HAND_BUILT = "answers-the-question"
OWNED = tuple(j for j in judges.JUDGES if j.name != HAND_BUILT)
MARKER = "[installed by the langfuse-workshop kit]"
ROOT_FILTER = {"type": "stringOptions", "column": "name", "operator": "any of", "value": [tracing.ROOT_NAME]}
VARIABLE_MAPPING = [
    {"variable": "question", "source": "input"},
    {"variable": "answer", "source": "output"},
]


@dataclass
class InstallReport:
    created: list[str] = field(default_factory=list)
    already_installed: list[str] = field(default_factory=list)
    rules_created: list[str] = field(default_factory=list)
    name_taken: list[str] = field(default_factory=list)
    hand_built_present: bool = False
    unrecognised: list[str] = field(default_factory=list)


def _pages(api: Any, path: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        body = api.get(path, **params).json()
        items += body.get("data") or []
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor:
            return items


def anthropic_connection(api: Any) -> dict[str, Any]:
    """The connection evaluators run on: one named `anthropic`, else the only Anthropic one."""
    body = api.get("/api/public/llm-connections", limit=100).json()
    connections = body.get("data") or []
    named = [c for c in connections if c.get("provider") == "anthropic"]
    if named:
        return named[0]
    by_adapter = [c for c in connections if c.get("adapter") == "anthropic"]
    if len(by_adapter) == 1:
        return by_adapter[0]
    raise KitError(
        EVAL_NO_CONNECTION,
        "Your Langfuse project has no Anthropic LLM connection yet, so nothing was installed.",
        "In Langfuse open Settings > LLM Connections, add one with provider name `anthropic` and the workshop key, then run this again.",
    )


def evaluator_body(spec: judges.JudgeSpec, provider: str) -> dict[str, Any]:
    return {
        "type": "llm_as_judge",
        "name": spec.name,
        "description": f"{spec.summary} {MARKER}",
        "prompt": spec.prompt,
        "modelConfig": {"provider": provider, "model": llm.MODEL},
        "variableMapping": VARIABLE_MAPPING,
        "outputDefinition": {
            "dataType": "BOOLEAN",
            "scoreReasoningInstructions": "One or two sentences explaining the verdict.",
            "scoreValueInstructions": "true when the answer passes the check, false when it fails.",
        },
    }


def rule_body(name: str, evaluator_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "enabled": True,
        "filter": [ROOT_FILTER],
        "evaluatorAssignments": [{"evaluatorId": evaluator_id}],
    }


def install(api: Any) -> InstallReport:
    connection = anthropic_connection(api)
    evaluators = _pages(api, "/api/public/v2/evaluators")
    rules = _pages(api, "/api/public/v2/evaluation-rules")
    report = InstallReport()

    known = {j.name for j in judges.JUDGES}
    report.hand_built_present = any(e.get("name") == HAND_BUILT for e in evaluators)
    report.unrecognised = sorted({e.get("name", "") for e in evaluators} - known)
    rule_names = {r.get("name") for r in rules}

    for spec in OWNED:
        same_name = [e for e in evaluators if e.get("name") == spec.name]
        ours = next((e for e in same_name if MARKER in (e.get("description") or "")), None)
        if ours is None and same_name:
            report.name_taken.append(spec.name)
            continue
        if ours is None:
            response = api.post("/api/public/v2/evaluators", json=evaluator_body(spec, connection["provider"]))
            response.raise_for_status()
            ours = response.json()
            report.created.append(spec.name)
        else:
            report.already_installed.append(spec.name)
        if spec.name not in rule_names:
            api.post("/api/public/v2/evaluation-rules", json=rule_body(spec.name, ours["id"])).raise_for_status()
            report.rules_created.append(spec.name)
    return report


def print_report(report: InstallReport) -> None:
    for spec in OWNED:
        if spec.name in report.created:
            console.say(f"  installed      {spec.name}")
        elif spec.name in report.already_installed:
            note = " (its rule was added)" if spec.name in report.rules_created else ""
            console.say(f"  already there  {spec.name}{note}")
    for name in report.name_taken:
        console.error(
            EVAL_NAME_TAKEN,
            f"An evaluator named `{name}` already exists and was not made by the kit, so it was skipped.",
            "Rename or delete that evaluator in Langfuse, then run this again.",
        )
    if report.hand_built_present:
        console.say(f"  yours          {HAND_BUILT} (built by you, left unchanged)")
    else:
        console.say(f"\nYour own evaluator `{HAND_BUILT}` isn't there yet. It's yours to build by hand: follow the README.")
    for name in report.unrecognised:
        console.say(f"  not recognised `{name}`. If you meant your own evaluator, its exact name is `{HAND_BUILT}`.")
    total = len(report.created) + len(report.already_installed) + int(report.hand_built_present)
    console.say(f"\n{total} of 5 workshop evaluators are in your project.")
