"""The agent's one tool: read-only SQL over the bundled house-price data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files

import duckdb

PARQUET = files("kit") / "data" / "uk_price_paid.parquet"
MAX_ROWS_TO_MODEL = 50
COUNT_LIMIT = 10_000

RUN_SQL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": (
            "Run one read-only DuckDB SQL query (SELECT or WITH) against the sales "
            "database and get the result rows back as text. The database covers every "
            "sale in scope, so a correct query always returns rows. If a query returns "
            "no rows, it has a mistake, often a misspelled town or a wrong date format: "
            "fix it and run it again."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The SQL query to run."}},
            "required": ["query"],
        },
    },
}

_LEADING_COMMENTS = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/|\s)*", re.DOTALL)


@dataclass
class SqlResult:
    text: str
    row_count: int


class Database:
    """An in-memory DuckDB with views over the bundled Parquet file."""

    def __init__(self) -> None:
        self.con = duckdb.connect(":memory:")
        path = str(PARQUET).replace("'", "''")
        self.con.execute(f"CREATE VIEW sales AS SELECT * FROM read_parquet('{path}')")
        self.con.execute(
            """
            CREATE VIEW monthly_summary AS
            SELECT
                CAST(date_trunc('month', date) AS DATE) AS month,
                town,
                count(*) AS sales,
                round(avg(price) / 1000) AS avg_price_gbp
            FROM sales
            GROUP BY 1, 2
            """
        )

    def run(self, query: str) -> SqlResult:
        """Run a query and format the result for the model. Errors come back as text."""
        body = _LEADING_COMMENTS.sub("", query).strip().rstrip(";").strip()
        first = body.split(None, 1)[0].upper() if body else ""
        if first not in ("SELECT", "WITH") or ";" in body:
            return SqlResult("Error: only a single SELECT or WITH query is allowed.", 0)
        try:
            cursor = self.con.execute(body)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(COUNT_LIMIT + 1)
        except duckdb.Error as exc:
            return SqlResult(f"Error: {exc}", 0)
        return SqlResult(_format(columns, rows), min(len(rows), COUNT_LIMIT))


def _format(columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "The query returned no rows."
    lines = [" | ".join(columns)]
    lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in rows[:MAX_ROWS_TO_MODEL]]
    if len(rows) > MAX_ROWS_TO_MODEL:
        total = f"more than {COUNT_LIMIT:,}" if len(rows) > COUNT_LIMIT else f"{len(rows):,}"
        lines.append(f"(Showing the first {MAX_ROWS_TO_MODEL} of {total} rows.)")
    return "\n".join(lines)
