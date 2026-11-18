---
name: install-evaluators
description: Install the workshop's four Langfuse evaluators into the attendee's Langfuse project by running the kit's installer command. Use when the attendee asks to install, add or set up the workshop evaluators.
---

# Install the workshop evaluators

The kit has a command that installs four LLM-as-a-judge evaluators into the attendee's Langfuse project. It only creates what is missing, never changes or deletes an evaluator, and never touches the evaluator the attendee built by hand.

## Steps

1. From the repository root, run:

   ```
   uv run kit install-evaluators
   ```

2. Show the attendee the command's output as it is. It lists each evaluator and its state, and says whether the attendee's own evaluator `answers-the-question` exists yet.

3. If the command cannot reach the network because your sandbox blocks it, ask the attendee to approve network access for this command, or to run the same command in their own terminal. Do not try another way to reach Langfuse.

4. If the output shows an error code such as `EVAL-NO-CONNECTION`, relay the message and its fix line to the attendee. Do not work around it.

## Rules

- Never print, read aloud or copy the contents of `.env`. It holds the attendee's keys.
- Do not edit the kit's code to change what the installer does.
- Do not create, change or delete evaluators any other way.
