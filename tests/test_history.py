import json

import pytest

from fake_langfuse import FakeLangfuse, respond, timeout
from kit import dataset, history, otlp, state
from kit.langfuse_api import LangfuseApi

NAMES = ["answers-the-question", "sql-matches-question", "plausible-figures", "states-data-limits", "professional-tone"]
ANCHOR = 1_800_000_000 * 1_000_000_000  # a fixed load time, in nanoseconds
DAY = 86_400


def make_record(n, offset_s):
    return {
        "key": f"h{n:03d}",
        "offset_s": offset_s,
        "version": "1.3.0",
        "customer": "acme",
        "scope": {"name": "langfuse-sdk", "version": "5.2.0"},
        "spans": [
            {"key": "0", "parent": None, "name": "sql-agent", "start_ms": 0, "end_ms": 4000,
             "attributes": {"langfuse.observation.type": "agent", "user.id": "acme", "langfuse.version": "1.3.0",
                            "langfuse.observation.input": "Q?", "langfuse.observation.output": "A."}},
            {"key": "1", "parent": "0", "name": "llm-call", "start_ms": 5, "end_ms": 1500,
             "attributes": {"langfuse.observation.type": "generation", "user.id": "acme", "langfuse.version": "1.3.0"}},
            {"key": "2", "parent": "0", "name": "run_sql", "start_ms": 1600, "end_ms": 1700,
             "attributes": {"langfuse.observation.type": "tool", "user.id": "acme", "langfuse.version": "1.3.0"}},
        ],
        "scores": {name: (n % 2 == 0 or name != "plausible-figures") for name in NAMES},
    }


SAMPLE = [make_record(1, 13 * DAY), make_record(2, 3 * DAY), make_record(3, 120)]


@pytest.fixture
def fake(kit_home):
    return FakeLangfuse()


def api_for(fake, sleeps=None):
    return LangfuseApi("https://cloud.langfuse.com", "pk-lf-1", "sk-lf-1", transport=fake.transport,
                       sleep=(sleeps.append if sleeps is not None else lambda s: None))


def spans_by_trace(fake):
    out = {}
    for span in fake.otlp_spans():
        out.setdefault(span["traceId"], []).append(span)
    return out


def attrs(span):
    return {a["key"]: list(a["value"].values())[0] for a in span["attributes"]}


def test_sample_load_sends_otlp_with_v4_header_and_complete_spans(fake):
    history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR)

    posts = fake.calls("POST", "/api/public/otel/v1/traces")
    assert posts and all(r.headers["x-langfuse-ingestion-version"] == "4" for r in posts)
    spans = fake.otlp_spans()
    assert len(spans) == 9
    for span in spans:
        assert int(span["startTimeUnixNano"]) < int(span["endTimeUnixNano"])
        a = attrs(span)
        assert a["user.id"] == "acme" and a["langfuse.version"] == "1.3.0"


def test_loaded_times_come_from_the_stored_anchor(fake):
    history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR)

    stored = state.load()["history"]["anchor_ns"]
    assert stored == ANCHOR
    roots = [s for s in fake.otlp_spans() if "parentSpanId" not in s]
    starts = sorted(int(s["startTimeUnixNano"]) for s in roots)
    # The newest sample trace is two minutes old, so every trace moves back to ten minutes.
    shift = 600 - 120
    expected = sorted(ANCHOR - (r["offset_s"] + shift) * 1_000_000_000 for r in SAMPLE)
    assert starts == expected
    assert ANCHOR - max(starts) >= 600 * 1_000_000_000
    assert ANCHOR - min(starts) <= 15 * DAY * 1_000_000_000


def test_scores_attach_to_root_observation_at_its_end_time(fake):
    history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR)

    roots = {s["traceId"]: s for s in fake.otlp_spans() if "parentSpanId" not in s}
    assert len(fake.scores) == 15
    for score in fake.scores.values():
        root = roots[score["traceId"]]
        assert score["observationId"] == root["spanId"]
        assert score["name"] in NAMES
        assert score["dataType"] == "BOOLEAN" and score["value"] in (0, 1)
        assert "comment" not in score
        end_ms = int(root["endTimeUnixNano"]) // 1_000_000
        assert score["timestamp"].endswith("Z")
        assert score["timestamp"].startswith(_iso_ms(end_ms)[:19])


def _iso_ms(ms):
    import datetime as dt

    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).isoformat()


def test_same_run_and_anchor_give_identical_score_ids_and_timestamps():
    shift = otlp.age_shift(SAMPLE)
    first = [otlp.scores(r, "run-a", ANCHOR, shift) for r in SAMPLE]
    second = [otlp.scores(r, "run-a", ANCHOR, shift) for r in SAMPLE]
    assert first == second
    other_run = [otlp.scores(r, "run-b", ANCHOR, shift) for r in SAMPLE]
    assert first != other_run


def test_resumed_load_reuses_the_stored_anchor_even_when_the_clock_moved(fake):
    fake.overrides["POST /api/public/scores"].append(timeout)
    first = history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR)
    assert first.scores_unsent == 15 and fake.scores == {}
    assert history.status(api_for(fake)) == history.PARTIAL

    history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR + 3_600 * 1_000_000_000)

    run_id = state.load()["history"]["run_id"]
    shift = otlp.age_shift(SAMPLE)
    expected = {s["id"]: s["timestamp"] for r in SAMPLE for s in otlp.scores(r, run_id, ANCHOR, shift)}
    assert {k: v["timestamp"] for k, v in fake.scores.items()} == expected
    assert len(fake.calls("POST", "/api/public/otel/v1/traces")) == 1
    assert state.load()["history"]["loaded"] is True


def test_completed_state_sends_nothing(fake):
    state.update(history={"run_id": "run-a", "loaded": True})
    assert history.status(api_for(fake)) == history.LOADED
    assert fake.requests == []


def test_rate_limited_batch_is_retried_and_timed_out_batch_is_skipped(fake):
    data = [make_record(n, DAY + n) for n in range(1, 36)]  # four batches
    sleeps = []
    fake.overrides["POST /api/public/otel/v1/traces"] += [
        respond(200),
        respond(429, headers={"Retry-After": "2"}),
        respond(200),
        timeout,
    ]

    report = history.load(api_for(fake, sleeps), data, now_ns=lambda: ANCHOR)

    local = state.load()["history"]
    assert sorted(local["sent"]) == [0, 1, 3]
    assert local["uncertain"] == [2]
    assert report.batches_uncertain == [2]
    assert sleeps == [2.0]
    assert local["loaded"] is True


def test_interrupted_load_resumes_at_the_next_unsent_batch(fake):
    data = [make_record(n, DAY + n) for n in range(1, 36)]
    state.update(history={"run_id": "run-a", "anchor_ns": ANCHOR, "sent": [0, 1], "uncertain": [], "scores_done": False})
    dataset.ensure_marker(api_for(fake), "run-a", ANCHOR)
    fake.requests.clear()

    history.load(api_for(fake), data, now_ns=lambda: ANCHOR)

    sent_keys = {attrs(s)["langfuse.observation.input"] for s in fake.otlp_spans() if "parentSpanId" not in s}
    assert len(fake.calls("POST", "/api/public/otel/v1/traces")) == 2
    resent = {otlp.trace_id("run-a", r["key"]) for r in data[:20]}
    assert not resent & {s["traceId"] for s in fake.otlp_spans()}
    assert len(fake.scores) == 35 * 5
    assert sent_keys == {"Q?"}


def test_marker_from_another_run_means_history_is_not_loaded_again(fake):
    dataset.ensure_marker(api_for(fake), "someone-elses-run", ANCHOR)
    assert history.status(api_for(fake)) == history.OTHER_RUN


def test_score_batch_answered_207_is_reported_and_not_retried(fake):
    fake.overrides["POST /api/public/scores"].append(respond(207, {"accepted": 10, "rejected": 5, "errors": []}))

    report = history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR)

    assert report.scores_rejected == 5
    assert len(fake.calls("POST", "/api/public/scores")) == 1


def test_dataset_items_keep_the_same_ids_on_a_second_pass(fake):
    dataset.add_ticket_items(api_for(fake))
    first = sorted(fake.dataset_items)
    dataset.add_ticket_items(api_for(fake))
    assert sorted(fake.dataset_items) == first
    assert first == [f"ticket-T{n:02d}" for n in range(1, 11)]
    assert len(fake.calls("POST", "/api/public/dataset-items")) == 20
    item = fake.dataset_items["ticket-T01"]
    assert item["datasetName"] == "workshop-golden" and item["expectedOutput"]


def test_marker_carries_run_id_and_anchor(fake):
    history.load(api_for(fake), SAMPLE, now_ns=lambda: ANCHOR)
    meta = fake.datasets["workshop-golden"]["metadata"]
    assert meta["run_id"] == state.load()["history"]["run_id"]
    assert int(meta["anchor_ns"]) == ANCHOR
    assert json.dumps(meta)


# --- The history step inside setup ----------------------------------------------

from kit import setup_flow
from kit.langfuse_api import Project
from kit.preflight import Services

VALUES = {"LANGFUSE_PUBLIC_KEY": "pk-lf-1", "LANGFUSE_SECRET_KEY": "sk-lf-1"}
PROJECT = Project(id="proj1", name="langfuse-workshop")


def step(fake, answer="y"):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return answer

    line = setup_flow.load_history(
        "https://cloud.langfuse.com", PROJECT, VALUES, Services(transport=fake.transport, sleep=lambda s: None),
        ask, records=lambda: SAMPLE,
    )
    return line, asked


def test_setup_asks_with_the_project_name_then_loads(fake):
    line, asked = step(fake)
    assert "`langfuse-workshop`" in asked[0]
    assert line.startswith("History: loaded")
    assert len(fake.otlp_spans()) == 9


def test_answering_no_sends_nothing(fake):
    line, _ = step(fake, answer="n")
    assert not [r for r in fake.requests if r.method == "POST"]
    assert "not loaded" in line


def test_second_setup_after_a_complete_load_sends_nothing(fake):
    step(fake)
    fake.requests.clear()
    line, asked = step(fake)
    assert fake.requests == [] and asked == []
    assert "already loaded" in line


def test_marker_from_another_run_prints_code_and_sends_no_span(fake, capsys):
    dataset.ensure_marker(api_for(fake), "someone-elses-run", ANCHOR)
    fake.requests.clear()
    line, asked = step(fake)
    assert "[HIST-ALREADY-LOADED]" in capsys.readouterr().err
    assert not fake.calls("POST", "/api/public/otel/v1/traces") and asked == []
