"""Load the recorded two weeks of history into the attendee's project, exactly once.

Two markers guard the load. The local state file records the project, the run ID, the
anchor time every timestamp derives from, and each span batch that was sent. A record
for a different project is ignored, so setup with a new project's keys loads it fresh. The golden dataset,
created before the first batch, carries the same run ID and anchor in its metadata so
a re-cloned repo can tell the project already holds history. Span batches are never
re-sent, because Langfuse would store re-sent spans twice.
"""

from __future__ import annotations

import gzip
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

import httpx

from kit import dataset, otlp, state
from kit.errors import HIST_ALREADY_LOADED, KitError

TRACES_PER_BATCH = 10
SCORES_PER_BATCH = 100
OTLP_PATH = "/api/public/otel/v1/traces"
SCORES_PATH = "/api/public/scores"
OTLP_HEADERS = {"x-langfuse-ingestion-version": "4"}

NOTHING = "none"
PARTIAL = "partial"
LOADED = "loaded"
OTHER_RUN = "other-run"


def records() -> list[dict[str, Any]]:
    path = files("kit") / "data" / "history.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def batches(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


@dataclass
class LoadReport:
    traces_sent: int = 0
    batches_uncertain: list[int] = field(default_factory=list)
    scores_accepted: int = 0
    scores_rejected: int = 0
    scores_unsent: int = 0
    resumed: bool = False


def local_record(api: Any, project_id: str) -> dict[str, Any]:
    """The local load record for this project, or {} when it belongs to another project."""
    local = state.load().get("history") or {}
    if not local.get("run_id"):
        return {}
    if "project_id" in local:
        return local if local["project_id"] == project_id else {}
    # Older records have no project: they belong to the project whose dataset carries their run ID.
    marker = dataset.marker(api)
    return local if marker and marker.get("run_id") == local["run_id"] else {}


def status(api: Any, project_id: str = "") -> str:
    """Where this project stands: nothing loaded, part loaded, loaded, or another run's history."""
    local = local_record(api, project_id)
    if local.get("loaded"):
        return LOADED
    marker = dataset.marker(api)
    if marker and marker.get("run_id") != local.get("run_id"):
        return OTHER_RUN
    return PARTIAL if local.get("run_id") else NOTHING


def already_loaded_error() -> KitError:
    return KitError(
        HIST_ALREADY_LOADED,
        "This project already holds workshop history from an earlier setup, so nothing was loaded again.",
        "Nothing to do if you can see the history in Langfuse. To start clean, create a new project and run setup with its keys.",
    )


def load(
    api: Any,
    data: list[dict[str, Any]],
    *,
    project_id: str = "",
    now_ns: Callable[[], int] = time.time_ns,
    progress: Callable[[str], None] = lambda _: None,
) -> LoadReport:
    """Send history spans, then scores, then the golden dataset items. Resumes a partial load."""
    local = local_record(api, project_id)
    report = LoadReport(resumed=bool(local.get("run_id")))
    if not local.get("run_id"):
        local = {"project_id": project_id, "run_id": uuid.uuid4().hex, "anchor_ns": now_ns(), "sent": [], "uncertain": [], "scores_done": False}
        _save(local)
    dataset.ensure_marker(api, local["run_id"], local["anchor_ns"])

    shift = otlp.age_shift(data)
    groups = batches(data, TRACES_PER_BATCH)
    for index, group in enumerate(groups):
        if index in local["sent"] or index in local["uncertain"]:
            continue
        body = otlp.spans_request(group, local["run_id"], local["anchor_ns"], shift)
        if _send(api, OTLP_PATH, body, OTLP_HEADERS):
            local["sent"].append(index)
            report.traces_sent += len(group)
        else:
            local["uncertain"].append(index)
        _save(local)
        progress(f"history traces: batch {index + 1} of {len(groups)}")
    report.batches_uncertain = list(local["uncertain"])

    if not local["scores_done"]:
        all_scores = [s for r in data for s in otlp.scores(r, local["run_id"], local["anchor_ns"], shift)]
        unsent = 0
        for group in batches(all_scores, SCORES_PER_BATCH):
            accepted, rejected, failed = _send_scores(api, group)
            report.scores_accepted += accepted
            report.scores_rejected += rejected
            unsent += failed
        # Scores carry fixed IDs and timestamps, so a later run can send them again safely.
        local["scores_done"] = unsent == 0
        report.scores_unsent = unsent
        _save(local)
        progress("history scores sent")

    dataset.add_ticket_items(api)
    local["loaded"] = local["scores_done"]
    _save(local)
    return report


def _save(local: dict[str, Any]) -> None:
    state.update(history=local)


def _send(api: Any, path: str, body: Any, headers: dict[str, str] | None = None) -> bool:
    """True when the batch was accepted. A timeout or server error leaves it uncertain."""
    try:
        response = api.post(path, json=body, headers=headers)
    except httpx.TimeoutException:
        return False
    if response.status_code >= 500:
        return False
    response.raise_for_status()
    return True


def _send_scores(api: Any, group: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Send one score batch: (accepted, rejected, not sent). A 207 is reported, not retried."""
    try:
        response = api.post(SCORES_PATH, json=group)
    except httpx.TimeoutException:
        return 0, 0, len(group)
    if response.status_code == 207:
        body = response.json() if response.content else {}
        rejected = int(body.get("rejected") or len(body.get("errors") or []))
        return len(group) - rejected, rejected, 0
    if response.status_code >= 500:
        return 0, 0, len(group)
    response.raise_for_status()
    return len(group), 0, 0
