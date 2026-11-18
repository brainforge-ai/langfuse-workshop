from types import SimpleNamespace as NS

from kit import judges

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
            block = NS(type="tool_use", id="v1", name="record_verdict", input={"reasoning": "Declined.", "verdict": False})
            return NS(content=[block])

    verdict = judges.score(judges.BY_NAME["answers-the-question"], "Q?", "I can't share that.", NS(messages=Model()))

    assert verdict == judges.Verdict("answers-the-question", False, "Declined.")
    prompt = calls[0]["messages"][0]["content"]
    assert "Q?" in prompt and "I can't share that." in prompt and "{{" not in prompt
    assert calls[0]["model"] == "claude-haiku-5-5"
