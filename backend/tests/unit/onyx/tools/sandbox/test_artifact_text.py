"""The line, read and find logic over a published file's text
(artifact_text.py): lines and pages, the numbered read with its character
limit, and the find engine with its time limit."""

import json
import time

import regex

from onyx.file_store.models import ArtifactText
from onyx.tools.tool_implementations.sandbox.artifact_text import (
    artifact_lines,
    find_lines,
    read_lines,
)
from onyx.tools.tool_implementations.sandbox.models import (
    FIND_LINE_MAX_CHARS,
    READ_LINE_MAX_CHARS,
)


def test_lines_end_at_any_newline_and_each_page_starts_a_line() -> None:
    lines, page_starts = artifact_lines(
        ArtifactText(
            pages=["a\r\nb\rc\n", "d", "", "e\n\nf"], paged=True, truncated=False
        )
    )
    assert lines == ["a", "b", "c", "d", "", "e", "", "f"]
    assert page_starts == [1, 4, 5, 6]

    lines, page_starts = artifact_lines(
        ArtifactText(pages=["one\ntwo\n"], paged=False, truncated=False)
    )
    assert (lines, page_starts) == (["one", "two"], [])


def test_a_read_numbers_its_lines_marks_pages_and_cuts_long_lines() -> None:
    long_line = "x" * (READ_LINE_MAX_CHARS + 5)
    lines = ["p1 a", "p1 b", "p2 a", long_line, "p3 a"]
    text, end = read_lines(lines, [1, 3, 5], 2, 5, 100_000)
    assert end == 5
    assert text == (
        "--- page 1 ---\n"
        "     2\tp1 b\n"
        "--- page 2 ---\n"
        "     3\tp2 a\n"
        f"     4\t{'x' * READ_LINE_MAX_CHARS}… [5 more characters]\n"
        "--- page 3 ---\n"
        "     5\tp3 a\n"
    )
    # Without pages, no page lines; a range past the end stops at the end.
    assert read_lines(["a", "b"], [], 2, 10, 100_000) == ("     2\tb\n", 2)
    assert read_lines(["a", "b"], [], 5, 10, 100_000) == ("", 4)


def test_a_read_stops_before_the_line_that_passes_its_json_limit() -> None:
    lines = ['say "hi"', "b", "c"]
    first = '     1\tsay "hi"\n'
    # Quotes, the tab and the newline each take two characters in JSON.
    cost = len(json.dumps(first)) - 2
    assert read_lines(lines, [], 1, 3, cost) == (first, 1)
    assert read_lines(lines, [], 1, 3, cost - 1) == ("", 0)


def _pattern(text: str) -> regex.Pattern[str]:
    return regex.compile(regex.escape(text), regex.IGNORECASE)


def test_find_pages_through_matches_with_context_and_pages() -> None:
    lines = [
        f"row {number} {'hit' if number % 3 == 0 else 'miss'}"
        for number in range(1, 13)
    ]
    page_starts = [1, 7]

    matches, seen, reached = find_lines(
        lines,
        page_starts,
        _pattern("HIT"),
        1,
        12,
        before=1,
        after=1,
        max_matches=2,
        offset=1,
        max_chars=100_000,
        timeout=5,
    )
    assert (seen, reached) == (4, None)
    assert [(match.line, match.page) for match in matches] == [(6, 1), (9, 2)]
    assert (matches[0].before, matches[0].after) == (["row 5 miss"], ["row 7 miss"])

    # The range limits the search; the last line has no line after it.
    matches, seen, _ = find_lines(
        lines,
        [],
        _pattern("hit"),
        10,
        12,
        before=0,
        after=2,
        max_matches=5,
        offset=0,
        max_chars=100_000,
        timeout=5,
    )
    assert seen == 1
    [match] = matches
    assert (match.line, match.page, match.after) == (12, None, [])


def test_find_cuts_a_long_line_around_its_match_and_keeps_to_its_limit() -> None:
    line = "a" * 1_000 + "needle" + "b" * 1_000
    matches, _, _ = find_lines(
        [line, "needle", "needle"],
        [],
        _pattern("needle"),
        1,
        3,
        before=0,
        after=1,
        max_matches=10,
        offset=0,
        max_chars=100_000,
        timeout=5,
    )
    shown = matches[0].text
    assert "needle" in shown and shown.startswith("…") and shown.endswith("…")
    assert len(shown) == FIND_LINE_MAX_CHARS + 2
    assert matches[1].before == [] and matches[1].after == ["needle"]

    first_cost = len(matches[0].model_dump_json()) + 1
    limited, seen, _ = find_lines(
        [line, "needle", "needle"],
        [],
        _pattern("needle"),
        1,
        3,
        before=0,
        after=1,
        max_matches=10,
        offset=0,
        max_chars=first_cost,
        timeout=5,
    )
    # The matches past the limit are seen but not shown.
    assert ([match.line for match in limited], seen) == ([1], 3)


def test_a_catastrophic_regex_ends_within_its_time_limit() -> None:
    lines = ["fine", "a" * 60 + "!", "aa"]
    started = time.monotonic()
    matches, seen, reached = find_lines(
        lines,
        [],
        regex.compile(r"(a|aa)+$"),
        1,
        3,
        before=0,
        after=0,
        max_matches=10,
        offset=0,
        max_chars=100_000,
        timeout=0.3,
    )
    assert time.monotonic() - started < 2
    assert (matches, seen, reached) == ([], 0, 2)
