import re
from pathlib import Path

from kit import cli, judges
from kit.errors import ALL_CODES

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_every_error_code_is_in_the_troubleshooting_table():
    table = README.split("## Troubleshooting", 1)[1]
    missing = [code for code in ALL_CODES if f"| `{code}` |" not in table]
    assert missing == []


def test_every_command_is_in_the_readme():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    missing = [name for name in sub.choices if f"uv run kit {name}" not in README]
    assert missing == []


def test_evaluator_one_prompt_block_matches_the_judge_spec():
    block = re.search(r"```text\n(.*?)\n```", README, re.DOTALL).group(1)
    assert block == judges.BY_NAME["answers-the-question"].prompt


def test_readme_names_the_kit_model_and_connection():
    from kit import llm

    assert f"`{llm.MODEL}`" in README
    assert f"Provider name: `{llm.CONNECTION_NAME}`" in README
    assert llm.BASE_URL in README
