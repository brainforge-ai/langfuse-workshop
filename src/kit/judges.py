"""The five LLM-as-a-judge evaluators, as data, plus a local runner for one verdict.

Each judge sees two variables: `question` (the root observation's input) and
`answer` (its output: the answer text, the last SQL query and the row count). Every
score is a boolean where true means healthy. Langfuse evaluators use the same prompt
text, so a local verdict and a Langfuse verdict come from the same instructions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from kit import llm

VARIABLES = ("question", "answer")

_SHARED = """\
You are reviewing one answer from Price Insight, an assistant that answers questions \
about house sales in England and Wales from HM Land Registry price paid data. The \
assistant writes SQL against a table of individual sales (price in whole pounds, \
date, outward postcode, property type, new-build flag, tenure, post town, local \
authority district, county). The data runs from January 2023 to the end of \
September 2026.

Question:
{{question}}

Assistant output (the answer, then the last SQL query it ran, then the row count):
{{answer}}
"""


@dataclass(frozen=True)
class JudgeSpec:
    name: str
    summary: str
    criteria: str

    @property
    def prompt(self) -> str:
        return f"{_SHARED}\n{self.criteria}\n\nReply true when the answer passes this check and false when it fails."


JUDGES: tuple[JudgeSpec, ...] = (
    JudgeSpec(
        name="answers-the-question",
        summary="The answer gives the customer a direct result for what they asked.",
        criteria="""\
Check: does the answer directly answer the question that was asked?
- Pass when the answer gives a specific result for the question, including a clear \
"there were none" when nothing matches.
- Fail when the answer declines, refuses, says it could not finish, asks the \
customer to rephrase, or answers a different question.
- Prices paid for individual properties are public record in this dataset, so \
declining to share one is a failure.
- Do not judge whether the figure is correct, only whether the question was answered.""",
    ),
    JudgeSpec(
        name="sql-matches-question",
        summary="The SQL computes what the question asks for.",
        criteria="""\
Check: does the last SQL query compute what the question asks for?
- The filters must match the question: place, property type, new-build status, \
tenure and the exact date range.
- The calculation must match the question: a count for "how many", the maximum for \
"highest", the median for "median" or "typical middle", the mean for "average".
- Place names: `town` is the post town and covers the whole town, for example \
LONDON covers every London borough. `district` is a smaller local authority area. \
A filter that covers only part of the place asked about is a failure.
- If no SQL was run, pass: other checks cover answers that skip the data.""",
    ),
    JudgeSpec(
        name="plausible-figures",
        summary="Every figure is believable for UK house sales.",
        criteria="""\
Check: are the figures in the answer plausible for house sales in England and Wales?
- A typical average or median home price is between about 80,000 and 1,500,000 \
pounds. A single home rarely sells for under 20,000 pounds.
- A town of any size records hundreds to tens of thousands of sales a year.
- Fail when a price or count is off by orders of magnitude, such as an average home \
price in the hundreds of pounds, or when a figure contradicts the rows implied by \
the SQL and row count.
- Pass when the answer states no figures.""",
    ),
    JudgeSpec(
        name="states-data-limits",
        summary="The answer flags incomplete recent data when it matters.",
        criteria="""\
Check: does the answer respect the limits of the data?
- Sales reach the Land Registry weeks or months after they complete, so the latest \
two to three months of data (July to September 2026) are always incomplete.
- When the question or answer covers that recent period, or compares it with \
earlier months, the answer must say the recent figures are incomplete and must not \
present a drop in recent sales or prices as fact.
- Pass when the question and answer do not involve that recent period.""",
    ),
    JudgeSpec(
        name="professional-tone",
        summary="The answer reads as plain, professional business English.",
        criteria="""\
Check: is the answer written in a plain, professional tone suitable for a business \
customer?
- Fail for slang, rhyming slang, jokes, role play, unusual forms of address, or \
anything a customer could find odd or unprofessional.
- A friendly sentence or a polite apology is fine.""",
    ),
)

BY_NAME = {j.name: j for j in JUDGES}

_VERDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "record_verdict",
        "description": "Record whether the answer passes the check.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string", "description": "One or two sentences explaining the verdict."},
                "verdict": {"type": "boolean", "description": "true when the answer passes the check."},
            },
            "required": ["reasoning", "verdict"],
        },
    },
}


@dataclass(frozen=True)
class Verdict:
    name: str
    value: bool
    reasoning: str


def render(spec: JudgeSpec, question: str, answer: str) -> str:
    values = {"question": question, "answer": answer}
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], spec.prompt)


def variables(text: str) -> set[str]:
    return set(re.findall(r"\{\{(\w+)\}\}", text))


# Reasoning tokens count against this budget, so it leaves room for the reasoning and the verdict.
JUDGE_MAX_OUTPUT_TOKENS = 4096


def score(spec: JudgeSpec, question: str, answer: str, llm_client: Any) -> Verdict:
    """Run one judge locally through the workshop model and return its verdict."""
    response = llm.create(
        llm_client,
        reasoning=True,
        max_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        messages=[{"role": "user", "content": render(spec, question, answer)}],
        tools=[_VERDICT_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_verdict"}},
    )
    for call in response.choices[0].message.tool_calls or []:
        if call.function.name == "record_verdict":
            verdict = json.loads(call.function.arguments)
            return Verdict(spec.name, _as_bool(verdict["verdict"]), str(verdict.get("reasoning", "")))
    raise ValueError(f"judge {spec.name} returned no verdict")


def _as_bool(value: Any) -> bool:
    """Some models send the boolean as a string."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)
