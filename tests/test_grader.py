"""The pull request grader in .github/scripts/grade_pr.py."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("grade_pr", ROOT / ".github/scripts/grade_pr.py")
grade_pr = importlib.util.module_from_spec(SPEC)
sys.modules["grade_pr"] = grade_pr
SPEC.loader.exec_module(grade_pr)


def starting_files():
    return {path: (ROOT / path).read_text(encoding="utf-8") for path in grade_pr.FILES}


def without_lines(files, wanted):
    """Drop every line whose fingerprint is in `wanted`."""
    return {
        path: "\n".join(
            line for line in text.splitlines() if grade_pr.fingerprint(line) not in wanted
        )
        for path, text in files.items()
    }


def test_every_fingerprint_matches_a_line_in_the_starting_code():
    files = starting_files()
    present = {path: grade_pr.fingerprints(text) for path, text in files.items()}
    missing = [
        (p.title, path, h)
        for p in grade_pr.PROBLEMS
        for group in p.groups
        for path, h in group
        if h not in present[path]
    ]
    assert missing == []


def test_starting_code_scores_zero():
    assert [ok for _, ok in grade_pr.grade(starting_files())] == [False] * len(grade_pr.PROBLEMS)


def test_each_problem_is_fixed_independently():
    for problem in grade_pr.PROBLEMS:
        wanted = {h for group in problem.groups for _, h in group}
        results = grade_pr.grade(without_lines(starting_files(), wanted))
        assert [p.title for p, ok in results if ok] == [problem.title]


def test_a_problem_with_two_groups_needs_both_changed():
    problem = next(p for p in grade_pr.PROBLEMS if len(p.groups) == 2)
    first = {h for _, h in problem.groups[0]}
    files = without_lines(starting_files(), first)
    assert not grade_pr.is_fixed(problem, files)


def test_whitespace_only_edits_do_not_count():
    files = {path: text.replace("- ", "-   ") for path, text in starting_files().items()}
    assert not any(ok for _, ok in grade_pr.grade(files))


def test_comment_lists_scores_and_hints_only_for_open_problems():
    files = without_lines(starting_files(), {h for g in grade_pr.PROBLEMS[0].groups for _, h in g})
    body = grade_pr.render(grade_pr.grade(files))
    assert body.startswith(grade_pr.MARKER)
    assert f"1 of {len(grade_pr.PROBLEMS)} fixed" in body
    assert grade_pr.PROBLEMS[0].hint not in body
    assert grade_pr.PROBLEMS[1].hint in body
