import argparse
import os
import subprocess
import sys

from kit import cli
from kit.errors import KitError

ARGS = argparse.Namespace()


def test_known_error_prints_code_and_fix_without_traceback(kit_home, capsys):
    def handler(_):
        raise KitError("LLM-KEY", "The workshop key was rejected.", "Run `uv run kit set-llm-key`.")

    assert cli.guarded(handler, ARGS) == 1
    err = capsys.readouterr().err
    assert "[LLM-KEY] The workshop key was rejected." in err
    assert "Fix: Run `uv run kit set-llm-key`." in err
    assert "Traceback" not in err


def test_unexpected_error_writes_log_and_hides_traceback(kit_home, capsys):
    def handler(_):
        raise ZeroDivisionError("boom")

    assert cli.guarded(handler, ARGS) == 1
    out = capsys.readouterr()
    assert "[KIT-UNEXPECTED]" in out.err
    assert "Traceback" not in out.err + out.out
    log = (kit_home / ".kit" / "kit.log").read_text(encoding="utf-8")
    assert "ZeroDivisionError: boom" in log


def _run_cp1252(code):
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, env=env, timeout=60
    )


def test_help_runs_under_cp1252_console():
    result = _run_cp1252("import sys; from kit.cli import main; sys.exit(main(['--help']))")
    assert result.returncode == 0, result.stderr
    assert b"usage: kit" in result.stdout


def test_error_with_unencodable_text_runs_under_cp1252_console(tmp_path):
    code = (
        "import sys, argparse\n"
        "from kit import cli, console\n"
        "from kit.errors import KitError\n"
        "console.configure()\n"
        "def h(_):\n"
        "    raise KitError('LLM-KEY', 'Prices rose \\u2192 \\u00a3300k \\U0001F600', 'Swap the key.')\n"
        "sys.exit(cli.guarded(h, argparse.Namespace()))\n"
    )
    env_code = f"import os; os.environ['KIT_HOME'] = {str(tmp_path)!r}\n" + code
    result = _run_cp1252(env_code)
    assert result.returncode == 1
    assert b"UnicodeEncodeError" not in result.stderr
    assert b"[LLM-KEY]" in result.stderr
