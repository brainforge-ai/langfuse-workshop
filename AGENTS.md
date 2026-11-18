# Notes for coding agents

This repository is a hands-on Langfuse workshop kit. Attendees run it with `uv run kit <command>`.

- To install the workshop's Langfuse evaluators, run `uv run kit install-evaluators` from the repository root and show the attendee its output. The same steps are in `.agents/skills/install-evaluators/SKILL.md`.
- If your sandbox blocks network access, ask the attendee to approve it or to run the command themselves.
- Never print or copy the contents of `.env`. It holds the attendee's keys.
- Run the offline tests with `uv run pytest`.
