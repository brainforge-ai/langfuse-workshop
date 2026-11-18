"""Setup, preflight and the LLM key switch, with no network and no real keys."""

from __future__ import annotations

import base64
import json
import ssl
from types import SimpleNamespace as NS

import httpx
import httpx2  # the HTTP package the openai SDK is built on
import openai
import pytest

from kit import config, llm, preflight, state
from kit.errors import KitError
from kit.langfuse_api import CLOUD_HOSTS, LangfuseApi
from kit.preflight import Services
from kit.setup_flow import run_set_llm_key, run_setup

US, EU = CLOUD_HOSTS[0][1], CLOUD_HOSTS[1][1]


@pytest.fixture(autouse=True)
def no_history_step(monkeypatch):
    """These tests cover preflight; the history step has its own tests."""
    monkeypatch.setattr("kit.setup_flow.load_history", lambda *a, **k: "History: (not part of this test)")

TRACE_PK = "pk-lf-trace-1111aaaa"
TRACE_SK = "sk-lf-trace-2222bbbb"
AGENT_PK = "pk-lf-agent-3333cccc"
AGENT_SK = "sk-lf-agent-4444dddd"
LLM_KEY = "sk-or-v1-workshop-5555eeee"
RESERVE_KEY = "sk-or-v1-reserve-6666ffff"

GOOD = {
    config.LANGFUSE_PUBLIC_KEY: TRACE_PK,
    config.LANGFUSE_SECRET_KEY: TRACE_SK,
    config.AGENT_PUBLIC_KEY: AGENT_PK,
    config.AGENT_SECRET_KEY: AGENT_SK,
    config.LLM_KEY: LLM_KEY,
}
SLOT_ORDER = (
    config.LANGFUSE_PUBLIC_KEY,
    config.LANGFUSE_SECRET_KEY,
    config.AGENT_PUBLIC_KEY,
    config.AGENT_SECRET_KEY,
    config.LLM_KEY,
)


class FakeLangfuse:
    """Answers the two Langfuse reads the kit makes, per host and key pair."""

    def __init__(self, accounts, traces=()):
        # accounts: {host: {(public, secret): (project_id, project_name)}}
        self.accounts = accounts
        self.traces = set(traces)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = f"{request.url.scheme}://{request.url.host}"
        user, _, password = (
            base64.b64decode(request.headers["authorization"].split()[1]).decode().partition(":")
        )
        project = self.accounts.get(host, {}).get((user, password))
        if project is None:
            return httpx.Response(401, json={"message": "Invalid credentials"})
        if request.url.path == "/api/public/projects":
            return httpx.Response(200, json={"data": [{"id": project[0], "name": project[1]}]})
        if request.url.path == "/api/public/v2/observations":
            trace_id = request.url.params["traceId"]
            data = [{"id": "obs-1", "traceId": trace_id}] if trace_id in self.traces else []
            return httpx.Response(200, json={"data": data, "meta": {}})
        return httpx.Response(404)

    def hosts_asked(self):
        return [f"{r.url.scheme}://{r.url.host}" for r in self.requests]


def both_pairs_on(host, project=("proj-1", "langfuse-workshop")):
    return {host: {(TRACE_PK, TRACE_SK): project, (AGENT_PK, AGENT_SK): project}}


def fake_llm(status=200, body=None, seen=None):
    """A real openai client pointed at OpenRouter, whose HTTP calls are answered locally."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if status == 200:
            return httpx2.Response(
                200,
                json={
                    "id": "gen-1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": llm.MODEL,
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        return httpx2.Response(status, json=body)

    def factory(key):
        def answer(request):
            if seen is not None:
                seen.append(key)  # one entry per model call, with the key that made it
            return handler(request)

        return openai.OpenAI(
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(answer)),
        )

    return factory


def services(lf, *, llm=None, hello_id="trace-hello-1", sleeps=None):
    lf.traces.add(hello_id)
    return Services(
        transport=httpx.MockTransport(lf),
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
        llm_client=llm or fake_llm(),
        send_hello=lambda: hello_id,
    )


def answers(values):
    """Prompt callables that answer each slot in order, by the slot's position."""
    queue = [values.get(k, "") for k in SLOT_ORDER]

    def ask(prompt=""):
        return queue.pop(0)

    return ask, ask


def setup_with(values, svc, existing=None):
    if existing is not None:
        config.write_env(existing)
    ask, ask_secret = answers(values)
    return run_setup(ask=ask, ask_secret=ask_secret, services=svc)


def code_of(excinfo):
    return excinfo.value.code


# --- Prefix checks: offline, and they name the slot ------------------------------------------


def test_reversed_tracing_pair_names_the_slot_and_makes_no_network_call(kit_home):
    lf = FakeLangfuse(both_pairs_on(US))
    values = dict(GOOD, **{config.LANGFUSE_PUBLIC_KEY: TRACE_SK, config.LANGFUSE_SECRET_KEY: TRACE_PK})
    with pytest.raises(KitError) as excinfo:
        setup_with(values, services(lf))
    assert code_of(excinfo) == "LF-KEY-SWAPPED"
    assert "tracing" in excinfo.value.message
    assert lf.requests == []


def test_llm_key_in_a_langfuse_slot_is_not_a_langfuse_key(kit_home):
    lf = FakeLangfuse(both_pairs_on(US))
    values = dict(GOOD, **{config.AGENT_SECRET_KEY: LLM_KEY})
    with pytest.raises(KitError) as excinfo:
        setup_with(values, services(lf))
    assert code_of(excinfo) == "LF-NOT-A-LANGFUSE-KEY"
    assert "agent secret key" in excinfo.value.message
    assert lf.requests == []


def test_langfuse_key_in_the_llm_slot_is_not_an_llm_key(kit_home):
    lf = FakeLangfuse(both_pairs_on(US))
    values = dict(GOOD, **{config.LLM_KEY: TRACE_SK})
    with pytest.raises(KitError) as excinfo:
        setup_with(values, services(lf))
    assert code_of(excinfo) == "LLM-NOT-AN-LLM-KEY"
    assert lf.requests == []


# --- Host and project checks -----------------------------------------------------------------


def test_pair_rejected_by_us_and_accepted_by_eu_stores_eu(kit_home, capsys):
    lf = FakeLangfuse(both_pairs_on(EU))
    assert setup_with(GOOD, services(lf)) == 0
    saved = state.load()
    assert saved["host"] == EU
    assert saved["project_id"] == "proj-1"
    assert saved["project_name"] == "langfuse-workshop"
    assert lf.hosts_asked()[:2] == [US, EU]
    out = capsys.readouterr()
    assert "[" not in out.err  # no error or warning code printed
    assert "langfuse-workshop" in out.out
    assert "uv run kit tickets" in out.out


def test_agent_pair_on_another_project_is_a_mismatch_naming_the_agent_slot(kit_home):
    lf = FakeLangfuse(
        {US: {(TRACE_PK, TRACE_SK): ("proj-1", "langfuse-workshop"), (AGENT_PK, AGENT_SK): ("proj-2", "other")}}
    )
    with pytest.raises(KitError) as excinfo:
        setup_with(GOOD, services(lf))
    assert code_of(excinfo) == "LF-PROJECT-MISMATCH"
    assert "agent" in excinfo.value.message


def test_tracing_pair_rejected_everywhere_is_a_keypair_error_naming_the_tracing_slot(kit_home):
    lf = FakeLangfuse({})
    with pytest.raises(KitError) as excinfo:
        setup_with(GOOD, services(lf))
    assert code_of(excinfo) == "LF-KEYPAIR"
    assert "tracing" in excinfo.value.message
    assert lf.hosts_asked() == [host for _, host in CLOUD_HOSTS]


def test_preset_base_url_is_used_as_is_and_no_other_host_is_tried(kit_home):
    custom = "https://langfuse.example.test"
    lf = FakeLangfuse(both_pairs_on(custom))
    existing = dict(GOOD, **{config.BASE_URL: custom})
    assert setup_with({}, services(lf), existing=existing) == 0
    assert set(lf.hosts_asked()) == {custom}
    assert state.load()["host"] == custom


# --- LLM check --------------------------------------------------------------------------------


def test_llm_check_answered_401_is_an_llm_key_error(kit_home):
    lf = FakeLangfuse(both_pairs_on(US))
    llm = fake_llm(401, {"error": {"code": 401, "message": "No auth credentials found"}})
    with pytest.raises(KitError) as excinfo:
        setup_with(GOOD, services(lf, llm=llm))
    assert code_of(excinfo) == "LLM-KEY"


def test_llm_check_unknown_model_is_an_llm_model_error(kit_home):
    lf = FakeLangfuse(both_pairs_on(US))
    unknown = fake_llm(404, {"error": {"code": 404, "message": f"No endpoints found for {llm.MODEL}."}})
    with pytest.raises(KitError) as excinfo:
        setup_with(GOOD, services(lf, llm=unknown))
    assert code_of(excinfo) == "LLM-MODEL"


@pytest.mark.parametrize(
    ("status", "message", "code"),
    [
        (402, "Insufficient credits. Add more using https://openrouter.ai/credits", "LLM-KEY"),
        (403, "Key limit exceeded (total limit).", "LLM-KEY"),
        (403, f"Model {llm.MODEL} is not in this key's guardrail allowlist.", "LLM-MODEL"),
        (429, "Rate limit exceeded", "LLM-RATE"),
        (503, "No available provider", "LLM-RATE"),
    ],
)
def test_llm_check_maps_openrouter_errors_to_codes(kit_home, status, message, code):
    lf = FakeLangfuse(both_pairs_on(US))
    llm = fake_llm(status, {"error": {"code": status, "message": message}})
    with pytest.raises(KitError) as excinfo:
        setup_with(GOOD, services(lf, llm=llm))
    assert code_of(excinfo) == code


def test_llm_check_turns_reasoning_off():
    requests = []

    class Model:
        def create(self, **request):
            requests.append(request)
            return NS(choices=[NS(message=NS(content="OK", tool_calls=None), finish_reason="stop")])

    preflight.check_llm_key("sk-or-v1-test", NS(llm_client=lambda key: NS(chat=NS(completions=Model()))))

    assert requests[0]["extra_body"] == {"reasoning": {"effort": "none"}}


# --- Network failures are never credential failures -------------------------------------------


def _raising(exc):
    def handler(request):
        raise exc

    return httpx.MockTransport(handler)


def test_certificate_failure_is_net_tls():
    cause = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    exc = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    exc.__cause__ = cause
    api = LangfuseApi(US, TRACE_PK, TRACE_SK, transport=_raising(exc))
    with pytest.raises(KitError) as excinfo:
        api.project()
    assert code_of(excinfo) == "NET-TLS"


def test_refused_connection_is_net_offline():
    api = LangfuseApi(US, TRACE_PK, TRACE_SK, transport=_raising(httpx.ConnectError("[Errno 111] Connection refused")))
    with pytest.raises(KitError) as excinfo:
        api.project()
    assert code_of(excinfo) == "NET-OFFLINE"


def test_429_with_retry_after_waits_through_the_injected_clock_and_retries_once():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"data": [{"id": "proj-1", "name": "langfuse-workshop"}]})

    sleeps = []
    api = LangfuseApi(US, TRACE_PK, TRACE_SK, transport=httpx.MockTransport(handler), sleep=sleeps.append)
    project = api.project()
    assert project.id == "proj-1"
    assert sleeps == [2.0]
    assert len(calls) == 2


# --- Prompts ----------------------------------------------------------------------------------


def test_rerun_with_full_env_keeps_every_value_on_enter_and_never_prints_a_full_secret(kit_home, capsys):
    lf = FakeLangfuse(both_pairs_on(US))
    prompts = []

    def enter(prompt=""):
        prompts.append(prompt)
        return ""

    config.write_env(GOOD)
    assert run_setup(ask=enter, ask_secret=enter, services=services(lf)) == 0
    assert config.read_env() == GOOD
    printed = capsys.readouterr()
    shown = printed.out + printed.err + "".join(prompts)
    for secret in (TRACE_SK, AGENT_SK, LLM_KEY, TRACE_PK, AGENT_PK):
        assert secret not in shown


def test_placeholders_copied_from_the_example_file_are_asked_for_and_replaced(kit_home, capsys):
    lf = FakeLangfuse(both_pairs_on(US))
    prompts = []
    queue = [GOOD[k] for k in SLOT_ORDER]

    def paste(prompt=""):
        prompts.append(prompt)
        return queue.pop(0)

    config.write_env(
        {
            config.LANGFUSE_PUBLIC_KEY: "pk-lf-...",
            config.LANGFUSE_SECRET_KEY: "sk-lf-...",
            config.AGENT_PUBLIC_KEY: "pk-lf-...",
            config.AGENT_SECRET_KEY: "sk-lf-...",
            config.LLM_KEY: "sk-or-...",
        }
    )
    assert run_setup(ask=paste, ask_secret=paste, services=services(lf)) == 0
    assert len(prompts) == 5
    assert not any("Enter keeps" in p for p in prompts)
    assert config.read_env() == GOOD
    assert "\r" not in capsys.readouterr().out  # not a terminal, so no spinner


def test_placeholder_is_not_kept_on_enter(kit_home, capsys):
    lf = FakeLangfuse(both_pairs_on(US))
    queue = ["", GOOD[config.LANGFUSE_PUBLIC_KEY]] + [""] * 4

    def enter_then_paste(prompt=""):
        return queue.pop(0)

    config.write_env(dict(GOOD, **{config.LANGFUSE_PUBLIC_KEY: "pk-lf-..."}))
    assert run_setup(ask=enter_then_paste, ask_secret=enter_then_paste, services=services(lf)) == 0
    assert "This one is needed" in capsys.readouterr().out
    assert config.read_env() == GOOD


def test_pasted_values_are_cleaned_before_saving(kit_home):
    lf = FakeLangfuse(both_pairs_on(US))
    values = dict(GOOD, **{config.LANGFUSE_SECRET_KEY: f'  "{TRACE_SK}"  '})
    assert setup_with(values, services(lf)) == 0
    assert config.read_env()[config.LANGFUSE_SECRET_KEY] == TRACE_SK


# --- Key switch -------------------------------------------------------------------------------


def test_set_llm_key_changes_only_the_llm_key_and_rechecks_it(kit_home, capsys):
    config.write_env(dict(GOOD, **{config.BASE_URL: US}))
    seen = []
    svc = Services(llm_client=fake_llm(seen=seen))
    assert run_set_llm_key(ask_secret=lambda prompt="": RESERVE_KEY, services=svc) == 0
    assert config.read_env() == dict(GOOD, **{config.BASE_URL: US, config.LLM_KEY: RESERVE_KEY})
    assert seen == [RESERVE_KEY]
    out = capsys.readouterr().out
    assert "LLM Connections" in out  # the second step of the switch, done in Langfuse
    assert RESERVE_KEY not in out


def test_set_llm_key_rejects_a_wrong_prefix_and_saves_nothing(kit_home):
    config.write_env(GOOD)
    seen = []
    svc = Services(llm_client=fake_llm(seen=seen))
    with pytest.raises(KitError) as excinfo:
        run_set_llm_key(ask_secret=lambda prompt="": TRACE_SK, services=svc)
    assert code_of(excinfo) == "LLM-NOT-AN-LLM-KEY"
    assert config.read_env() == GOOD
    assert seen == []


# --- Hello trace ------------------------------------------------------------------------------


def test_unconfirmed_hello_trace_warns_with_a_link_and_setup_continues(kit_home, capsys):
    lf = FakeLangfuse(both_pairs_on(US))
    svc = services(lf)
    lf.traces.clear()  # the read finds nothing for the hello trace
    assert setup_with(GOOD, svc) == 0
    out = capsys.readouterr()
    assert "LF-TRACE-UNCONFIRMED" in out.err
    assert f"{US}/project/proj-1/traces/trace-hello-1" in out.err
    assert "uv run kit tickets" in out.out


def test_hello_trace_that_shows_up_after_the_read_lag_is_confirmed_without_a_warning(kit_home, capsys):
    lf = FakeLangfuse(both_pairs_on(US))

    class Clock(list):
        def append(self, seconds):
            super().append(seconds)
            if len(self) == 5:  # Langfuse makes the trace readable a few checks in
                lf.traces.add("trace-hello-1")

    sleeps = Clock()
    svc = services(lf, sleeps=sleeps)
    lf.traces.clear()
    assert setup_with(GOOD, svc) == 0
    out = capsys.readouterr()
    assert "LF-TRACE-UNCONFIRMED" not in out.err
    assert sum(sleeps) <= 30


def test_hello_trace_goes_through_the_sdk_as_one_root_observation(kit_home):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from kit.preflight import send_hello_trace

    config.write_env(dict(GOOD, **{config.LANGFUSE_PUBLIC_KEY: "pk-lf-hello-sdk-test"}))
    state.update(host=US)
    exporter = InMemorySpanExporter()
    trace_id = send_hello_trace(span_exporter=exporter)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].parent is None
    assert format(spans[0].context.trace_id, "032x") == trace_id
    assert json.dumps(dict(spans[0].attributes))  # attributes are plain data
