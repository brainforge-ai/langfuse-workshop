"""Grade a workshop pull request and post the result as one comment on it.

Run by .github/workflows/grade.yml on the base branch. It reads the pull request's
files through the GitHub API as plain text and never runs code from the pull request.

Each problem is a set of line fingerprints from the starting code. A problem counts
as fixed when, in every group, at least one of its lines is gone or changed.
Fingerprints are hashes, so this file does not print the lines it looks for.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

PROMPTS = "src/kit/agent/prompts.py"
NOTES = "src/kit/agent/schema_notes.md"
TOOLS = "src/kit/agent/tools.py"
FILES = (PROMPTS, NOTES, TOOLS)
MARKER = "<!-- langfuse-workshop-grade -->"


@dataclass(frozen=True)
class Problem:
    title: str
    hint: str
    groups: tuple[tuple[tuple[str, str], ...], ...]


PROBLEMS = (
    Problem(
        "Ticket T02: the agent won't give the top Bristol price",
        "`answers-the-question` flags it. Read the rules in the system prompt, `src/kit/agent/prompts.py`.",
        (
            (
                (PROMPTS, "c533c3bc081fafc1"),
                (PROMPTS, "452ab24fef3581c8"),
                (PROMPTS, "339e2207b751ad72"),
            ),
        ),
    ),
    Problem(
        "Ticket T07: the agent gives the average when asked for the median",
        "`sql-matches-question` flags it. Read the SQL tips in `src/kit/agent/schema_notes.md`.",
        (((NOTES, "ed30f0a6a04f9b76"),),),
    ),
    Problem(
        "Ticket T09: a Birmingham average of £271",
        "`plausible-figures` flags it. Compare what the `monthly_summary` view in "
        "`src/kit/agent/tools.py` returns with what the schema notes say it holds.",
        (((TOOLS, "3c3dd376aa3139bb"), (NOTES, "e3f2d89e87bddd64")),),
    ),
    Problem(
        "London answers since release 1.3.0",
        "`sql-matches-question` fails on London questions from 1.3.0. Find the schema note added in that release.",
        (((NOTES, "b2ebdd4b924b4c47"),),),
    ),
    Problem(
        "Recent months read as a collapse in sales",
        "`states-data-limits` flags it. Check what the schema notes claim about how complete the data is.",
        (((NOTES, "c1b2d4ea6ccf1805"),),),
    ),
    Problem(
        "Answers for the postcode districts E20 and SW1A",
        "`professional-tone` flags them. Read the whole system prompt in `src/kit/agent/prompts.py`.",
        (
            ((PROMPTS, "042f6b0e1bfbb996"), (PROMPTS, "6c4b2eb6e8ffe2c6")),
            ((PROMPTS, "32b6de99d9691158"), (PROMPTS, "52ae27bc59f19dcc")),
        ),
    ),
)


def fingerprint(line: str) -> str:
    normal = re.sub(r"\s+", " ", line.strip()).lower()
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()[:16]


def fingerprints(text: str | None) -> set[str]:
    return {fingerprint(line) for line in (text or "").splitlines()}


def is_fixed(problem: Problem, files: dict[str, str | None]) -> bool:
    present = {path: fingerprints(files.get(path)) for path in FILES}
    return all(any(h not in present[path] for path, h in group) for group in problem.groups)


def grade(files: dict[str, str | None]) -> list[tuple[Problem, bool]]:
    return [(p, is_fixed(p, files)) for p in PROBLEMS]


def render(results: list[tuple[Problem, bool]]) -> str:
    fixed = sum(ok for _, ok in results)
    lines = [
        MARKER,
        f"## Workshop grade: {fixed} of {len(results)} fixed",
        "",
        "| | Problem |",
        "|---|---|",
    ]
    lines += [f"| {'✅' if ok else '⬜'} | {p.title} |" for p, ok in results]
    missed = [p for p, ok in results if not ok]
    if missed:
        lines += ["", "<details><summary>Hints for the ones still open</summary>", ""]
        lines += [f"- **{p.title}.** {p.hint}" for p in missed]
        lines += ["", "</details>"]
    else:
        lines += ["", "You found every one. Nice work."]
    lines += [
        "",
        "A problem counts as fixed when the lines behind it change. Prove each fix with "
        '`uv run kit ask "<the question>"` and check the new trace\'s scores in Langfuse. '
        "Push more commits and this comment updates.",
    ]
    return "\n".join(lines)


class GitHub:
    def __init__(self, token: str, repo: str) -> None:
        self.token, self.repo = token, repo

    def call(self, method: str, path: str, body: dict | None = None, raw: bool = False):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}/{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read().decode("utf-8")
        return data if raw else json.loads(data or "null")

    def file(self, path: str, ref: str) -> str | None:
        quoted = urllib.parse.quote(path)
        try:
            return self.call("GET", f"contents/{quoted}?ref={ref}", raw=True)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            raise

    def upsert_comment(self, number: int, body: str) -> None:
        comments = self.call("GET", f"issues/{number}/comments?per_page=100")
        mine = [c for c in comments if c["user"]["type"] == "Bot" and MARKER in c["body"]]
        if mine:
            self.call("PATCH", f"issues/comments/{mine[0]['id']}", {"body": body})
        else:
            self.call("POST", f"issues/{number}/comments", {"body": body})


def main() -> int:
    github = GitHub(os.environ["GH_TOKEN"], os.environ["REPO"])
    files = {path: github.file(path, os.environ["HEAD_SHA"]) for path in FILES}
    body = render(grade(files))
    github.upsert_comment(int(os.environ["PR_NUMBER"]), body)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(body.replace(MARKER, "") + "\n")
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
