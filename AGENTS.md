# Notes for coding agents

This repository is a hands-on Langfuse workshop kit. Attendees run it with `uv run kit <command>`.

- To install the workshop's Langfuse evaluators, run `uv run kit install-evaluators` from the repository root and show the attendee its output. The same steps are in `.agents/skills/install-evaluators/SKILL.md`.
- If your sandbox blocks network access, ask the attendee to approve it or to run the command themselves.
- Never print or copy the contents of `.env`. It holds the attendee's keys.
- To investigate the agent's failures in Langfuse, follow `.agents/skills/investigate-in-langfuse/SKILL.md`. It uses the Langfuse MCP server named `langfuse`.
- With the Langfuse MCP server, only read. The one write allowed is `upsertDatasetItem` into the `workshop-golden` dataset. Never create, change, test or delete evaluators, evaluation rules, scores, prompts, datasets or dashboards, and never run batch evaluations.
- Do not run `uv run kit mcp` yourself. Its output contains the attendee's secret key, so they run it in their own terminal.
- Run the offline tests with `uv run pytest`.
