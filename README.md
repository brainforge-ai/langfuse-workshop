# Langfuse Workshop: the on-call incident

You just joined the on-call rotation for **Price Insight**, a SQL analytics agent that answers questions about UK house prices. It shipped two weeks ago. Customers are filing tickets, some answers are wrong, and nobody knows why.

In this workshop you will use [Langfuse](https://langfuse.com) to find out. You will trace the agent, read what it did, build an evaluator that flags bad answers, let your coding agent install more evaluators, and then hunt through two weeks of scored history for the root causes.

The agent answers questions over a bundled slice of the UK house-price dataset that ClickHouse publishes as its `uk_price_paid` example dataset. Everything runs on your laptop except the model calls and your own Langfuse Cloud project.

## Before you start

1. A free Langfuse Cloud account at [cloud.langfuse.com](https://cloud.langfuse.com). No credit card is needed.
2. [git](https://git-scm.com/downloads).
3. [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the right Python version for you.
4. A coding agent: Claude Code, Cursor, Codex or similar.
5. A laptop. macOS, Windows and Linux all work, and Windows needs no WSL.
6. The workshop LLM key from the 1Password link the presenters share.

## 1. Set up (about 15 minutes)

1. If you cloned this repo before the session, run `git pull` first so you have the final version. Otherwise clone it:

   ```
   git clone https://github.com/brainforge-ai/langfuse-workshop.git
   cd langfuse-workshop
   ```

2. In Langfuse, create a new project named `langfuse-workshop`. Use a new project even if you already have one.
3. In that project open **Settings > API Keys** and create two key pairs. The first is for the app's tracing, the second is for your coding agent. Copy each secret key before you close its dialog, because Langfuse shows it only once.
4. Run setup and paste the keys when asked:

   ```
   uv run kit setup
   ```

   It asks for the tracing pair, the agent pair and the workshop LLM key. Secret keys stay hidden while you paste. Setup finds your Langfuse region by itself, checks every key, sends a hello trace, then asks before it loads two weeks of history into your project. Loading takes about a minute.

5. Open **Tracing** in Langfuse and set the time range to the last 14 days. You should see about 84 traces named `sql-agent`, each with five scores. Those scores are the last two weeks of offline eval runs, made with the same judge prompts you will use, so Langfuse lists their source as API rather than an evaluator. They can take about 10 minutes to appear in charts.

> **Joining late?** Run every step above in order. Run setup before you build any evaluator, so the history loads before evaluators start judging new traces.

## 2. Work the tickets

Ten customers have filed tickets. Send them all through the agent:

```
uv run kit tickets
```

Each ticket prints the complaint, the question, the agent's answer and a link to its trace. You can also send one ticket with `uv run kit ticket 3`, or ask your own question with `uv run kit ask "How many flats sold in York in 2025?"`.

Open the traces. Each one has a root observation named `sql-agent` with the question as input and, as output, the answer, the last SQL the agent ran and its row count. Inside it are the model calls (`llm-call`) and the SQL tool calls (`run_sql`). Compare each answer with what the customer expected. Some of them went wrong. Which ones, and where in the trace can you see it?

## 3. Build your first evaluator by hand

An evaluator uses an LLM as a judge to score every new trace. You will build the first one yourself.

**Add the LLM connection.** The workshop model runs on [OpenRouter](https://openrouter.ai), which speaks the OpenAI API, so the connection uses the `openai` adapter. In Langfuse open **Settings > LLM Connections** and add a connection:

- Provider name: `openrouter`
- LLM adapter: `openai`
- API key: the workshop LLM key
- Under **Advanced Settings**, set the base URL to `https://openrouter.ai/api/v1`, turn off the default models, and add `anthropic/claude-haiku-5.5` as a custom model.

**Create the evaluator.** Open **Evaluators** and create a new evaluator. The form has three numbered parts.

1. **Define evaluation method.**
   - Use: **LLM-as-a-judge**, with `openrouter / anthropic/claude-haiku-5.5` from the model chooser next to it.
   - In the message box, replace the default text ("Evaluate the quality of the response...") with the whole block below.
   - Under the box, set **Return a** to **boolean** score.

```text
You are reviewing one answer from Price Insight, an assistant that answers questions about house sales in England and Wales from HM Land Registry price paid data. The assistant writes SQL against a table of individual sales (price in whole pounds, date, outward postcode, property type, new-build flag, tenure, post town, local authority district, county). The data runs from January 2023 to the end of September 2026.

Question:
{{question}}

Assistant output (the answer, then the last SQL query it ran, then the row count):
{{answer}}

Check: does the answer directly answer the question that was asked?
- Pass when the answer gives a specific result for the question, including a clear "there were none" when nothing matches.
- Fail when the answer declines, refuses, says it could not finish, asks the customer to rephrase, or answers a different question.
- Prices paid for individual properties are public record in this dataset, so declining to share one is a failure.
- Do not judge whether the figure is correct, only whether the question was answered.

Reply true when the answer passes this check and false when it fails.
```

2. **Map variables to data.** Langfuse lists the two variables from the prompt. Map `{{question}}` to **Input** and `{{answer}}` to **Output**.
3. **Name evaluator.** Name: `answers-the-question`. Type it exactly, because the score uses the same name.

**Before you click Create evaluator,** look at the **Test with sample observations** panel on the right. The evaluator will run on whatever that panel's filter matches. It starts with `isRootObservation: true`. Add a second filter, **Name**, and pick `sql-agent` from its dropdown, so it judges only the agent's answers.

Click **Create evaluator**. In the **Evaluator saved** dialog:

- Keep **Reuse the configured filters** selected. It shows the filters from the panel.
- Leave **Run evaluator on past observations matching these filters** off. The history already carries scores, and judging it again would spend the shared key.
- Leave **Sampling** at 100%.
- Click **Execute**, not **Skip execution**.

Now send three tickets again, for example `uv run kit ticket 2`, `uv run kit ticket 5` and `uv run kit ticket 1`. After a minute or two the new traces show an `answers-the-question` score. The history traces keep only the scores they came with.

## 4. Let your coding agent install the rest

Ask your coding agent to install the workshop evaluators. It finds the skill in `.claude/skills/` or `.agents/skills/`, which runs one command. You can also run that command yourself:

```
uv run kit install-evaluators
```

It installs four more evaluators (`sql-matches-question`, `plausible-figures`, `states-data-limits` and `professional-tone`) with their rules, using the agent key pair. It only creates what is missing, never changes anything, and leaves your `answers-the-question` alone. Running it twice is safe. If your agent's sandbox blocks network access, approve it or run the command in your own terminal.

Send the tickets again with `uv run kit tickets` and watch all five scores arrive on the new traces.

## 5. Hunt the root causes

The tickets were the visible symptoms. The scored history holds causes nobody has noticed yet. Start by hand, then hand the search to your coding agent.

**By hand.**

1. In **Tracing**, keep the 14-day range and open the score charts. Look for a score that changed over time, then filter traces by that score being false.
2. Slice by **Version** and by **User** (each customer is a user) to see which segment broke and when.
3. Open a failing trace and read the SQL and the system prompt inside its `llm-call`. Then find the line in this repo that caused it.

**With your coding agent.**

4. Connect your agent to Langfuse's MCP server. In your own terminal, not through the agent, run:

   ```
   uv run kit mcp
   ```

   It prints the settings for Claude Code, Codex and Cursor, using your agent key pair. The output contains your secret key, so paste it only into your agent's settings. In Claude Code, this repo's `.claude/settings.json` lets the agent read your project and add dataset items, and blocks every other change.

5. Ask your agent: "Use the Langfuse MCP server to find why the agent's answers fail, and show me the cause in this repo." It reports each cause with a failing trace before it changes anything.
6. Add a failing trace to the dataset `workshop-golden` with the correct answer as its expected output. Your agent can do this, or do it by hand: open the trace, choose **Add to dataset**, pick `workshop-golden`, and replace the expected output.
7. Fix the cause and prove it with `uv run kit ask "<the same question>"`. The new trace should pass its evaluator.

## If the LLM key stops working

When the shared key hits its cap, the kit prints `LLM-KEY` with two steps. Do both:

1. Run `uv run kit set-llm-key` and paste the reserve key the presenters share.
2. In Langfuse open **Settings > LLM Connections**, edit `openrouter` and paste the same key, so your evaluators keep working.

The workshop key stops working after Nov 19. Any OpenRouter API key works in its place, in the same two places.

## Troubleshooting

Every error prints a code and a fix line. Running `uv run kit setup` again re-checks your keys and never loads history twice.

| Code | What it means | What to do |
|---|---|---|
| `LF-KEY-SWAPPED` | A public key is in a secret slot, or the other way round. | Paste the `pk-lf-` key as the public key and the `sk-lf-` key as the secret key. |
| `LF-NOT-A-LANGFUSE-KEY` | A Langfuse slot holds something else, often the LLM key. | Copy the key from Langfuse **Settings > API Keys**. |
| `LF-KEYPAIR` | Langfuse did not accept a key pair. | Copy both keys of that pair again, or create a new pair. |
| `LF-PROJECT-MISMATCH` | The agent pair belongs to a different project. | Create the agent pair in the `langfuse-workshop` project. |
| `LF-TRACE-UNCONFIRMED` | The hello trace has not shown up yet. | Open the printed link after a minute. Setup carries on. |
| `LLM-NOT-AN-LLM-KEY` | The LLM slot holds a Langfuse key. | Paste the workshop key from 1Password. It starts with `sk-or-`. |
| `LLM-KEY` | The LLM key was rejected, capped or revoked. | Follow the two steps in "If the LLM key stops working". |
| `LLM-RATE` | The LLM key is busy. | Wait 30 seconds and run the command again. |
| `LLM-MODEL` | The key may not call the workshop model, or no provider can serve it right now. | Tell a presenter. |
| `NET-TLS` | Something on the network intercepts secure connections. | Switch to another network, such as a phone hotspot. |
| `NET-OFFLINE` | The kit cannot reach the internet. | Check your Wi-Fi. |
| `HIST-ALREADY-LOADED` | This project already holds workshop history. | Nothing to do if you can see it. To start clean, create a new project and run setup with its keys. |
| `EVAL-NO-CONNECTION` | The project has no OpenRouter LLM connection. | Add the `openrouter` connection from step 3, then install again. |
| `EVAL-NAME-TAKEN` | An evaluator the kit did not make already uses one of its names. | Rename or delete that evaluator, then install again. |
| `KIT-NOT-SET-UP` | The kit has no saved keys. | Run `uv run kit setup`. |
| `KIT-UNEXPECTED` | Something went wrong inside the kit. | Show the log file it names to a presenter. |

If the key prompt in setup hangs or will not accept a paste, copy `.env.example` to `.env`, fill in the five values with a text editor, and run `uv run kit setup` again, pressing Enter at each prompt to keep them.

## If you want more

- One more cause hides in the history: some averages look high in towns where a single large sale lands. Find which property type carries those sales and decide how the agent should handle them.
- Ask the agent about the postcode districts `E20` and `SW1A` and see which evaluator notices.
- Read `src/kit/judges.py` and write a sixth evaluator for a failure you found.

## Data

Contains HM Land Registry data (c) Crown copyright and database right 2026. This data is licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). See `NOTICE`.

## License

Code is MIT-licensed. See `LICENSE`.
