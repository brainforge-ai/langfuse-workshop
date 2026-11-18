"""Price Insight: answers a question by writing SQL, running it and reading the rows.

Each run is one Langfuse trace. Its root observation, `sql-agent`, holds the question
as input and, as output, the answer, the last SQL run and its row count. Model calls
and tool calls are child observations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langfuse import Langfuse, propagate_attributes

from kit import llm
from kit.agent.prompts import SCHEMA_NOTES, system_prompt
from kit.agent.tools import RUN_SQL, Database
from kit.tracing import APP_VERSION, ROOT_NAME

MAX_TOOL_STEPS = 6
STEP_LIMIT_ANSWER = f"I could not finish this question in {MAX_TOOL_STEPS} steps."


@dataclass
class AgentResult:
    question: str
    answer: str
    sql: str | None = None
    row_count: int = 0
    trace_id: str | None = None
    tool_steps: int = 0
    queries: list[str] = field(default_factory=list)

    def output_text(self) -> str:
        return f"{self.answer}\n\nSQL:\n{self.sql or '(none)'}\n\nRows: {self.row_count}"


def run(
    question: str,
    *,
    langfuse: Langfuse,
    llm_client: Any,
    customer: str,
    schema_notes: str = SCHEMA_NOTES,
    version: str = APP_VERSION,
    db: Database | None = None,
) -> AgentResult:
    """Answer one question and trace it. The caller flushes the Langfuse client."""
    db = db or Database()
    result = AgentResult(question=question, answer="")
    with langfuse.start_as_current_observation(name=ROOT_NAME, as_type="agent", input=question) as root:
        result.trace_id = root.trace_id
        with propagate_attributes(user_id=customer, version=version):
            _loop(question, result, db, llm_client, system_prompt(schema_notes), langfuse)
        root.update(output=result.output_text())
    return result


def _loop(question: str, result: AgentResult, db: Database, llm_client: Any, system: str, langfuse: Langfuse) -> None:
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    while True:
        response = _call_model(langfuse, llm_client, system, messages)
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not tool_uses:
            result.answer = text or "(no answer)"
            return
        if result.tool_steps >= MAX_TOOL_STEPS:
            result.answer = STEP_LIMIT_ANSWER
            return
        messages.append({"role": "assistant", "content": [_block(b) for b in response.content]})
        tool_results = []
        for use in tool_uses:
            query = str(use.input.get("query", ""))
            with langfuse.start_as_current_observation(name="run_sql", as_type="tool", input=query) as span:
                sql_result = db.run(query)
                span.update(output=sql_result.text)
            result.tool_steps += 1
            result.sql, result.row_count = query, sql_result.row_count
            result.queries.append(query)
            tool_results.append({"type": "tool_result", "tool_use_id": use.id, "content": sql_result.text})
        messages.append({"role": "user", "content": tool_results})


def _call_model(langfuse: Langfuse, llm_client: Any, system: str, messages: list[dict[str, Any]]) -> Any:
    with langfuse.start_as_current_observation(
        name="llm-call", as_type="generation", model=llm.MODEL, input=[{"role": "system", "content": system}, *messages]
    ) as generation:
        response = llm.create(
            llm_client,
            system=system,
            messages=messages,
            tools=[RUN_SQL],
            tool_choice={"type": "auto"},
        )
        usage = getattr(response, "usage", None)
        generation.update(
            output=[_block(b) for b in response.content],
            usage_details={
                "input": getattr(usage, "input_tokens", 0) or 0,
                "output": getattr(usage, "output_tokens", 0) or 0,
            },
        )
    return response


def _block(block: Any) -> dict[str, Any]:
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": "text", "text": block.text}
