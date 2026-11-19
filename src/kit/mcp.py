"""`kit mcp`: connect the attendee's coding agent to Langfuse's hosted MCP server.

The server logs in with the agent key pair. Its write tools are on by default, so the
agent gets read access plus one write: adding items to the `workshop-golden` dataset.
"""

from __future__ import annotations

import base64
import json

from kit import config, console, tracing
from kit.errors import not_set_up

SERVER_NAME = "langfuse"
DATASET_WRITE = "upsertDatasetItem"

# Read-only tools the investigation needs, as listed by the server's tools/list.
READ_TOOLS = (
    "listObservations",
    "getObservation",
    "getObservationFieldSchema",
    "getObservationFilterSchema",
    "getObservationFilterValues",
    "listScores",
    "getScore",
    "listScoreConfigs",
    "getScoreConfig",
    "queryMetrics",
    "getMetricsSchema",
    "listDatasets",
    "getDataset",
    "listDatasetItems",
    "getDatasetItem",
    "listEvaluators",
    "getEvaluator",
    "listEvaluationRules",
    "getEvaluationRule",
    "listComments",
    "getComment",
    "getHealth",
)
ALLOWED_TOOLS = (*READ_TOOLS, DATASET_WRITE)

# Every tool the server marks as not read-only, except the dataset write above.
WRITE_TOOLS = (
    "createTextPrompt",
    "createChatPrompt",
    "updatePromptLabels",
    "createSkillVersion",
    "updateSkillLabels",
    "updateSkillTags",
    "createAnnotationQueue",
    "createAnnotationQueueItem",
    "updateAnnotationQueueItem",
    "deleteAnnotationQueueItem",
    "createAnnotationQueueAssignment",
    "deleteAnnotationQueueAssignment",
    "createComment",
    "upsertDataset",
    "batchUpsertDatasetItems",
    "deleteDatasetItem",
    "createDatasetRunItem",
    "deleteDatasetRun",
    "createScore",
    "createScoreConfig",
    "updateScoreConfig",
    "deleteScoreConfig",
    "createModel",
    "deleteModel",
    "testEvaluator",
    "createEvaluator",
    "updateEvaluator",
    "deleteEvaluator",
    "createEvaluationRule",
    "updateEvaluationRule",
    "attachEvaluatorToEvaluationRule",
    "detachEvaluatorFromEvaluationRule",
    "deleteEvaluationRule",
    "setDefaultEvaluationModel",
    "deleteDefaultEvaluationModel",
    "runBatchEvaluation",
    "createDashboardWidget",
    "updateDashboardWidget",
    "deleteDashboardWidget",
    "createDashboard",
    "updateDashboard",
    "deleteDashboard",
    "addDashboardPlacement",
    "updateDashboardPlacement",
    "deleteDashboardPlacement",
    "submitFeedback",
)


def endpoint(host: str) -> str:
    return f"{host.rstrip('/')}/api/public/mcp"


def auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"Basic {token}"


def claude_permissions() -> dict[str, list[str]]:
    """The `permissions` block of `.claude/settings.json`."""
    prefix = f"mcp__{SERVER_NAME}__"
    return {
        "allow": [prefix + name for name in ALLOWED_TOOLS],
        "deny": [prefix + name for name in WRITE_TOOLS],
    }


def instructions(host: str, public_key: str, secret_key: str) -> str:
    url = endpoint(host)
    header = auth_header(public_key, secret_key)
    enabled = ", ".join(f'"{name}"' for name in ALLOWED_TOOLS)
    cursor = json.dumps({"mcpServers": {SERVER_NAME: {"url": url, "headers": {"Authorization": header}}}}, indent=2)
    return f"""\
Connect your coding agent to Langfuse. Run or paste this in your own terminal or editor,
not through the agent: it contains your agent secret key.

Claude Code (run in this folder; the repo's .claude/settings.json keeps it read-only):

  claude mcp add --transport http {SERVER_NAME} {url} --header "Authorization: {header}"

Codex (add to ~/.codex/config.toml, then restart Codex):

  [mcp_servers.{SERVER_NAME}]
  url = "{url}"
  http_headers = {{ "Authorization" = "{header}" }}
  enabled_tools = [{enabled}]

Cursor (add to .cursor/mcp.json in this folder, then restart Cursor, and leave only
read tools plus {DATASET_WRITE} switched on under Settings > MCP):

{cursor}

Then ask your agent to investigate. AGENTS.md tells it which Langfuse tools it may use.
"""


def run() -> int:
    values = config.read_env()
    public, secret = values.get(config.AGENT_PUBLIC_KEY), values.get(config.AGENT_SECRET_KEY)
    if not public or not secret:
        raise not_set_up()
    console.say(instructions(tracing.host(), public, secret))
    return 0
