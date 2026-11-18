# Langfuse Workshop: the on-call incident

You just joined the on-call rotation for **Price Insight**, a SQL analytics agent that answers questions about UK house prices. It shipped two weeks ago. Customers are filing tickets, some answers are wrong, and nobody knows why.

In this workshop you will use [Langfuse](https://langfuse.com) to find out. You will trace the agent, read what it did, build an evaluator that flags bad answers, let your coding agent install more evaluators, and then hunt through two weeks of scored history for the root causes.

The agent answers questions over a bundled slice of the UK house-price dataset that ClickHouse publishes as its `uk_price_paid` example dataset. Everything runs on your laptop except the model calls and your own Langfuse Cloud project.

## Before the session

Please do these before you arrive:

1. Create a free Langfuse Cloud account at [cloud.langfuse.com](https://cloud.langfuse.com). No credit card is needed. Create one project named `langfuse-workshop`.
2. Install [git](https://git-scm.com/downloads).
3. Install [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the right Python version for you.
4. Have a coding agent ready: Claude Code, Cursor, Codex or similar.
5. Bring a laptop. macOS, Windows and Linux all work, and Windows needs no WSL.

**Don't run anything in this repo yet.** The full steps are added here before the session starts, and we'll do setup together in the first fifteen minutes. We share the workshop LLM key at the start, so no other accounts are needed.

## Data

Contains HM Land Registry data (c) Crown copyright and database right 2026. This data is licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). See `NOTICE`.

## License

Code is MIT-licensed. See `LICENSE`.
