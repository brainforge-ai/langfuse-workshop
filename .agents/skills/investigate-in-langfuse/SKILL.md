---
name: investigate-in-langfuse
description: Investigate why the Price Insight agent gives bad answers, using the Langfuse MCP server to read its traces and evaluator scores, then trace each failure to its cause in this repo. Use when the attendee asks you to investigate, hunt causes, or find what broke in the agent's history.
---

# Investigate the agent's failures in Langfuse

The attendee's Langfuse project holds two weeks of `sql-agent` traces, each scored by five evaluators: `answers-the-question`, `sql-matches-question`, `plausible-figures`, `states-data-limits` and `professional-tone`. A false score marks a bad answer. Your job is to find what made the agent fail, show the evidence, and point to the cause in this repo.

You reach Langfuse through the MCP server named `langfuse`. If its tools are missing, ask the attendee to run `uv run kit mcp` in their own terminal and follow what it prints. Do not run that command yourself: its output contains their secret key.

## Steps

1. **Find what fails.** Use `queryMetrics` on the `scores-boolean` view, grouped by score name and by day, over the last 14 days. Langfuse rejects ranges longer than 14 days. Look for an evaluator whose false count changes over time.
2. **Find who and when.** Break the false scores down by release (the observation's `version`) and by customer (`userId`). Say which segment broke and when.
3. **Read failing traces.** Use `listScores` with the evaluator's name and value `false` to get trace IDs, then `listObservations` with that `traceId`. Read the `sql-agent` input and output, the SQL in `run_sql`, and the system prompt in the first `llm-call`. Compare with a passing trace for the same kind of question.
4. **Find the cause in the repo.** Look at the system prompt in `src/kit/agent/prompts.py`, the schema notes in `src/kit/agent/schema_notes.md`, and the tool description in `src/kit/agent/tools.py`. Quote the line that explains the failure.
5. **Report before changing anything.** For each cause, tell the attendee: the evaluator that caught it, the segment and dates, one failing trace ID, the line at fault, and the fix you propose. Wait for their go-ahead before editing code.
6. **Save a test case.** When the attendee agrees, add one failing trace to the `workshop-golden` dataset: find its ID with `listDatasets`, then call `upsertDatasetItem` with the question as input, the correct answer as `expectedOutput`, and `sourceTraceId` set to the failing trace.
7. **Prove the fix.** After the fix, ask the attendee to run `uv run kit ask "<the same question>"` and check that the new trace passes its evaluator.

## Rules

- Read only. The one Langfuse write you may make is `upsertDatasetItem` into `workshop-golden`.
- Never create, change, test or delete evaluators, evaluation rules, scores, prompts, datasets or dashboards, and never run batch evaluations. Those spend the shared model key or change the attendee's project.
- Never print, read aloud or copy the contents of `.env`. It holds the attendee's keys.
