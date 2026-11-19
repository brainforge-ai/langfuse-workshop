import base64
import json
from pathlib import Path

from kit import cli, history, mcp

ROOT = Path(__file__).resolve().parent.parent


def test_claude_settings_match_the_tool_lists():
    settings = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"] == mcp.claude_permissions()


def test_agent_may_read_and_add_dataset_items_but_not_spend_or_change_the_project():
    assert not set(mcp.ALLOWED_TOOLS) & set(mcp.WRITE_TOOLS)
    assert "upsertDatasetItem" in mcp.ALLOWED_TOOLS
    for risky in ("runBatchEvaluation", "testEvaluator", "createEvaluator", "deleteEvaluator", "createScore"):
        assert risky in mcp.WRITE_TOOLS


def test_instructions_point_every_agent_at_the_project_region_with_the_agent_key_pair():
    text = mcp.instructions("https://us.cloud.langfuse.com/", "pk-lf-agent", "sk-lf-agent")
    token = base64.b64encode(b"pk-lf-agent:sk-lf-agent").decode()
    assert "claude mcp add --transport http langfuse https://us.cloud.langfuse.com/api/public/mcp" in text
    assert text.count(f"Basic {token}") == 3
    assert 'enabled_tools = ["listObservations"' in text


def test_mcp_without_saved_keys_says_to_run_setup(kit_home, capsys):
    assert cli.main(["mcp"]) == 1
    assert "[KIT-NOT-SET-UP]" in capsys.readouterr().err


def test_investigation_skill_files_are_identical():
    claude = (ROOT / ".claude/skills/investigate-in-langfuse/SKILL.md").read_bytes()
    agents = (ROOT / ".agents/skills/investigate-in-langfuse/SKILL.md").read_bytes()
    assert claude == agents


def test_history_fits_in_the_mcp_servers_fourteen_day_query_window():
    # The oldest trace starts 13 days before the load, so a 14-day query an hour later still finds it.
    assert max(r["offset_s"] for r in history.records()) <= 13 * 86_400
