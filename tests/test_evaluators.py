import json
from types import SimpleNamespace as NS

from kit import judges, llm

NAMES = [
    "answers-the-question",
    "sql-matches-question",
    "plausible-figures",
    "states-data-limits",
    "professional-tone",
]


def test_five_judges_with_exact_names():
    assert [j.name for j in judges.JUDGES] == NAMES


def test_each_judge_prompt_uses_exactly_question_and_answer():
    for judge in judges.JUDGES:
        assert judges.variables(judge.prompt) == {"question", "answer"}, judge.name


def test_local_runner_returns_the_models_boolean_verdict():
    calls = []

    class Model:
        def create(self, **request):
            calls.append(request)
            arguments = json.dumps({"reasoning": "Declined.", "verdict": False})
            call = NS(id="v1", type="function", function=NS(name="record_verdict", arguments=arguments))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[call]), finish_reason="tool_calls")])

    verdict = judges.score(
        judges.BY_NAME["answers-the-question"], "Q?", "I can't share that.", NS(chat=NS(completions=Model()))
    )

    assert verdict == judges.Verdict("answers-the-question", False, "Declined.")
    prompt = calls[0]["messages"][0]["content"]
    assert "Q?" in prompt and "I can't share that." in prompt and "{{" not in prompt
    assert calls[0]["model"] == llm.MODEL
    assert calls[0]["tool_choice"] == {"type": "function", "function": {"name": "record_verdict"}}


def test_local_judges_keep_the_models_default_reasoning_with_room_for_it():
    calls = []

    class Model:
        def create(self, **request):
            calls.append(request)
            arguments = json.dumps({"reasoning": "Fine.", "verdict": True})
            call = NS(id="v1", type="function", function=NS(name="record_verdict", arguments=arguments))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[call]), finish_reason="tool_calls")])

    judges.score(judges.BY_NAME["professional-tone"], "Q?", "A.", NS(chat=NS(completions=Model())))

    assert "reasoning" not in (calls[0].get("extra_body") or {})
    # Reasoning tokens count against max_tokens, so a judge needs far more than the verdict itself.
    assert calls[0]["max_tokens"] >= 4096


# --- Installer -------------------------------------------------------------------

import base64

import pytest

from fake_langfuse import FakeLangfuse, respond
from kit import evaluators
from kit.errors import KitError
from kit.langfuse_api import LangfuseApi

OWNED = NAMES[1:]


def connection(provider="openrouter", base_url="https://openrouter.ai/api/v1"):
    return {"id": f"c-{provider}", "provider": provider, "adapter": "openai", "baseURL": base_url}


def api_for(fake, sleeps=None):
    return LangfuseApi("https://cloud.langfuse.com", "pk-lf-agent", "sk-lf-agent", transport=fake.transport,
                       sleep=(sleeps.append if sleeps is not None else lambda s: None))


def body(request):
    import json

    return json.loads(request.content)


@pytest.fixture
def fake():
    f = FakeLangfuse()
    f.llm_connections.append(connection())
    yield f
    assert not [r for r in f.requests if r.method in ("PATCH", "DELETE")]


def test_fresh_project_gets_four_evaluators_and_four_rules(fake):
    report = evaluators.install(api_for(fake))
    assert sorted(report.created) == sorted(OWNED)
    assert len(fake.calls("POST", "/api/public/v2/evaluators")) == 4
    assert len(fake.calls("POST", "/api/public/v2/evaluation-rules")) == 4


def test_evaluator_body_pins_provider_and_model_and_maps_question_and_answer(fake):
    evaluators.install(api_for(fake))
    for request in fake.calls("POST", "/api/public/v2/evaluators"):
        sent = body(request)
        assert sent["modelConfig"] == {"provider": "openrouter", "model": llm.MODEL}
        assert sent["variableMapping"] == [
            {"variable": "question", "source": "input"},
            {"variable": "answer", "source": "output"},
        ]
        assert sent["outputDefinition"]["dataType"] == "BOOLEAN"
        assert "target" not in sent and "version" not in sent


def test_rule_body_is_enabled_with_one_evaluator_and_a_typed_name_filter(fake):
    evaluators.install(api_for(fake))
    ids = {e["name"]: e["id"] for e in fake.evaluators}
    for request in fake.calls("POST", "/api/public/v2/evaluation-rules"):
        sent = body(request)
        assert sent["enabled"] is True
        assert sent["evaluatorAssignments"] == [{"evaluatorId": ids[sent["name"]]}]
        assert sent["filter"] == [{"type": "stringOptions", "column": "name", "operator": "any of", "value": ["sql-agent"]}]


def test_second_run_with_all_five_present_creates_nothing(fake, capsys):
    fake.evaluators.append({"id": "mine", "name": "answers-the-question", "description": "built by hand"})
    evaluators.install(api_for(fake))
    fake.requests.clear()

    report = evaluators.install(api_for(fake))
    evaluators.print_report(report)

    assert not [r for r in fake.requests if r.method == "POST"]
    assert sorted(report.already_installed) == sorted(OWNED)
    assert "5 of 5 workshop evaluators" in capsys.readouterr().out


def test_without_evaluator_one_it_installs_four_and_says_evaluator_one_is_theirs(fake, capsys):
    report = evaluators.install(api_for(fake))
    evaluators.print_report(report)
    out = capsys.readouterr().out
    assert len(report.created) == 4
    assert "`answers-the-question` isn't there yet" in out
    assert "answers-the-question" not in [body(r)["name"] for r in fake.calls("POST", "/api/public/v2/evaluators")]


def test_same_name_without_kit_marker_is_skipped_and_others_install(fake, capsys):
    fake.evaluators.append({"id": "theirs", "name": "plausible-figures", "description": "someone else's"})
    report = evaluators.install(api_for(fake))
    evaluators.print_report(report)
    assert report.name_taken == ["plausible-figures"]
    assert len(report.created) == 3
    assert "[EVAL-NAME-TAKEN]" in capsys.readouterr().err


def test_no_llm_connection_stops_before_creating_anything(fake):
    fake.llm_connections.clear()
    with pytest.raises(KitError) as err:
        evaluators.install(api_for(fake))
    assert err.value.code == "EVAL-NO-CONNECTION"
    assert not [r for r in fake.requests if r.method == "POST"]


def test_connection_named_openrouter_wins_over_others(fake):
    fake.llm_connections[:] = [connection("openai", None), connection("my-router"), connection("openrouter")]
    evaluators.install(api_for(fake))
    assert body(fake.calls("POST", "/api/public/v2/evaluators")[0])["modelConfig"]["provider"] == "openrouter"


def test_single_openrouter_connection_under_another_name_is_used(fake):
    fake.llm_connections[:] = [connection("openai", None), connection("my-router")]
    evaluators.install(api_for(fake))
    assert body(fake.calls("POST", "/api/public/v2/evaluators")[0])["modelConfig"]["provider"] == "my-router"


def test_plain_openai_connection_is_not_used(fake):
    fake.llm_connections[:] = [connection("openai", None)]
    with pytest.raises(KitError) as err:
        evaluators.install(api_for(fake))
    assert err.value.code == "EVAL-NO-CONNECTION"


def test_misnamed_evaluator_is_reported_beside_the_expected_name(fake, capsys):
    fake.evaluators.append({"id": "typo", "name": "answer-the-question", "description": ""})
    evaluators.print_report(evaluators.install(api_for(fake)))
    out = capsys.readouterr().out
    assert "not recognised `answer-the-question`" in out
    assert "exact name is `answers-the-question`" in out


def test_missing_rule_for_an_installed_evaluator_is_added_alone(fake):
    evaluators.install(api_for(fake))
    fake.rules[:] = [r for r in fake.rules if r["name"] != "states-data-limits"]
    fake.requests.clear()

    report = evaluators.install(api_for(fake))

    assert not fake.calls("POST", "/api/public/v2/evaluators")
    assert [body(r)["name"] for r in fake.calls("POST", "/api/public/v2/evaluation-rules")] == ["states-data-limits"]
    assert report.rules_created == ["states-data-limits"]


def test_rate_limit_is_waited_out_and_retried(fake):
    sleeps = []
    fake.overrides["POST /api/public/v2/evaluators"].append(respond(429, headers={"Retry-After": "3"}))
    report = evaluators.install(api_for(fake, sleeps))
    assert sleeps == [3.0]
    assert len(report.created) == 4


def test_every_request_uses_the_agent_key_pair(fake):
    evaluators.install(api_for(fake))
    expected = "Basic " + base64.b64encode(b"pk-lf-agent:sk-lf-agent").decode()
    assert fake.requests and all(r.headers["authorization"] == expected for r in fake.requests)


def test_skill_files_are_identical():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    claude = (root / ".claude/skills/install-evaluators/SKILL.md").read_bytes()
    agents = (root / ".agents/skills/install-evaluators/SKILL.md").read_bytes()
    assert claude == agents
