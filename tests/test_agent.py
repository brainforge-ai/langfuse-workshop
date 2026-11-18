import json
import re
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from kit import cli, config, state, tickets, tracing
from kit.agent import agent
from kit.agent.tools import Database


def tool_call(query, call_id="t1"):
    return NS(
        content=[NS(type="tool_use", id=call_id, name="run_sql", input={"query": query})],
        usage=NS(input_tokens=10, output_tokens=5),
    )


def text(answer):
    return NS(content=[NS(type="text", text=answer)], usage=NS(input_tokens=10, output_tokens=5))


class ScriptedModel:
    """Stands in for the provider client: returns scripted responses in order."""

    def __init__(self, *responses, repeat_last=False):
        self.responses = list(responses)
        self.repeat_last = repeat_last
        self.calls = []
        self.messages = self

    def create(self, **request):
        self.calls.append(request)
        if self.repeat_last and len(self.responses) == 1:
            return self.responses[0]
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_counter = iter(range(10_000))


def make_langfuse():
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=f"pk-lf-test-{next(_counter)}",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        span_exporter=exporter,
    )
    return client, exporter


def root_span(client, exporter):
    client.flush()
    roots = [s for s in exporter.get_finished_spans() if s.name == "sql-agent"]
    assert len(roots) == 1
    return roots[0]


@pytest.fixture(scope="module")
def db():
    return Database()


def test_root_observation_holds_question_answer_sql_and_row_count(db):
    client, exporter = make_langfuse()
    query = "SELECT count(*) AS n FROM sales WHERE town = 'LEEDS' AND year(date) = 2025"
    model = ScriptedModel(tool_call(query), text("Leeds had 10,900 sales in 2025."))

    result = agent.run("How many sales in Leeds in 2025?", langfuse=client, llm_client=model, customer="acme", db=db)

    root = root_span(client, exporter)
    assert root.attributes["langfuse.observation.input"] == "How many sales in Leeds in 2025?"
    assert root.attributes["langfuse.observation.output"] == (
        f"Leeds had 10,900 sales in 2025.\n\nSQL:\n{query}\n\nRows: 1"
    )
    assert root.attributes["user.id"] == "acme"
    assert root.attributes["langfuse.version"] == "1.3.0"
    assert result.trace_id
    children = [s for s in exporter.get_finished_spans() if s.name != "sql-agent"]
    assert {s.name for s in children} == {"llm-call", "run_sql"}


def test_loop_stops_after_six_tool_calls(db):
    client, exporter = make_langfuse()
    model = ScriptedModel(tool_call("SELECT 1"), repeat_last=True)

    result = agent.run("Keep going", langfuse=client, llm_client=model, customer="acme", db=db)

    assert result.tool_steps == 6
    assert result.answer == agent.STEP_LIMIT_ANSWER
    assert root_span(client, exporter).attributes["langfuse.observation.output"].startswith(agent.STEP_LIMIT_ANSWER)
    assert len([s for s in exporter.get_finished_spans() if s.name == "run_sql"]) == 6


def test_large_result_is_cut_to_fifty_rows_with_a_note(db):
    out = db.run("SELECT price FROM sales LIMIT 200")
    lines = out.text.splitlines()
    assert lines[0] == "price"
    assert len(lines) == 1 + 50 + 1
    assert lines[-1] == "(Showing the first 50 of 200 rows.)"
    assert out.row_count == 200


@pytest.mark.parametrize("statement", ["DROP VIEW sales", "SELECT 1; DROP VIEW sales", "COPY sales TO 'x.csv'"])
def test_non_select_statement_is_refused_and_run_continues(db, statement):
    client, exporter = make_langfuse()
    model = ScriptedModel(tool_call(statement), text("Sorry, I could not run that."))

    result = agent.run("Do something", langfuse=client, llm_client=model, customer="acme", db=db)

    assert result.answer == "Sorry, I could not run that."
    tool_result = model.calls[1]["messages"][-1]["content"][0]["content"]
    assert tool_result.startswith("Error: only a single SELECT or WITH query")
    assert db.run("SELECT count(*) FROM sales").row_count == 1


def test_requests_use_the_kit_model_settings(db):
    client, _ = make_langfuse()
    model = ScriptedModel(text("Hello."))
    agent.run("Hi", langfuse=client, llm_client=model, customer="acme", db=db)
    request = model.calls[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["max_tokens"] == 1024
    assert request["thinking"] == {"type": "disabled"}
    assert request["tool_choice"] == {"type": "auto"}
    assert not {"temperature", "top_p", "top_k"} & set(request)


# --- Commands, driven through the real CLI entry point -------------------------


def status_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    return cls("rejected", response=response, body=None)


@pytest.fixture
def set_up_kit(kit_home, monkeypatch):
    """A kit that has finished setup, with tracing captured in memory."""
    config.write_env(
        {
            config.LANGFUSE_PUBLIC_KEY: "pk-lf-1",
            config.LANGFUSE_SECRET_KEY: "sk-lf-1",
            config.LLM_KEY: "sk-ant-first",
        }
    )
    state.update(host="https://cloud.langfuse.com", project_id="proj1")
    client, exporter = make_langfuse()
    flushes = []
    real_flush = client.flush

    def flush():
        flushes.append(True)
        real_flush()

    client.flush = flush
    monkeypatch.setattr(tracing, "client", lambda span_exporter=None: client)
    return NS(exporter=exporter, flushes=flushes, home=kit_home)


def provider(monkeypatch, behaviour):
    """Replace the provider client; `behaviour(api_key)` returns the scripted model."""
    seen = []

    def factory(api_key, **_):
        seen.append(api_key)
        return behaviour(api_key)

    monkeypatch.setattr(anthropic, "Anthropic", factory)
    return seen


def test_rejected_key_prints_two_step_switch_then_recovers_after_key_change(set_up_kit, monkeypatch, capsys):
    def behaviour(key):
        if key == "sk-ant-first":
            return ScriptedModel(status_error(anthropic.AuthenticationError, 401))
        return ScriptedModel(text("Fine now."))

    keys = provider(monkeypatch, behaviour)

    assert cli.main(["ask", "How many sales?"]) == 1
    err = capsys.readouterr().err
    assert "[LLM-KEY]" in err
    assert "kit set-llm-key" in err and "LLM Connections" in err
    assert "Traceback" not in err

    values = config.read_env()
    values[config.LLM_KEY] = "sk-ant-reserve"
    config.write_env(values)

    assert cli.main(["ask", "How many sales?"]) == 0
    assert "A: Fine now." in capsys.readouterr().out
    assert keys == ["sk-ant-first", "sk-ant-reserve"]


def test_rate_limit_on_every_retry_prints_wait_message(set_up_kit, monkeypatch, capsys):
    provider(monkeypatch, lambda key: ScriptedModel(status_error(anthropic.RateLimitError, 429)))
    assert cli.main(["ask", "How many sales?"]) == 1
    err = capsys.readouterr().err
    assert "[LLM-RATE]" in err and "Wait" in err


def test_flush_runs_when_the_agent_fails_partway(set_up_kit, monkeypatch):
    provider(
        monkeypatch,
        lambda key: ScriptedModel(tool_call("SELECT 1"), status_error(anthropic.InternalServerError, 500)),
    )
    assert cli.main(["ask", "How many sales?"]) == 1
    assert set_up_kit.flushes == [True]


def test_ask_prints_answer_and_trace_link(set_up_kit, monkeypatch, capsys):
    provider(monkeypatch, lambda key: ScriptedModel(text("About 16,000.")))
    assert cli.main(["ask", "How many sales in Manchester?"]) == 0
    out = capsys.readouterr().out
    assert "A: About 16,000." in out
    assert re.search(r"Trace: https://cloud\.langfuse\.com/project/proj1/traces/[0-9a-f]{32}", out)


def test_ask_before_setup_says_to_run_setup(kit_home, capsys):
    assert cli.main(["ask", "How many sales?"]) == 1
    assert "[KIT-NOT-SET-UP]" in capsys.readouterr().err


def test_unknown_ticket_number_prints_a_plain_line(kit_home, capsys):
    assert cli.main(["ticket", "11"]) == 1
    out = capsys.readouterr()
    assert "There is no ticket 11." in out.out
    assert "Traceback" not in out.err


def test_ticket_file_holds_ten_complete_tickets():
    items = tickets.load()
    assert [t.id for t in items] == [f"T{n:02d}" for n in range(1, 11)]
    for t in items:
        assert t.question and t.customer and t.expected and t.complaint


def test_ticket_file_is_valid_utf8_json():
    from importlib.resources import files

    json.loads((files("kit") / "data" / "tickets.json").read_text(encoding="utf-8"))
