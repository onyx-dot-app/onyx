"""The lines and pages of a published file's text (file_store/utils.py:
get_or_extract_artifact_text), for library_read and library_find: numbered
lines, page starts, the read and the find over them."""

import json
import time
from bisect import bisect_right
from collections.abc import Sequence

import regex

from onyx.file_store.models import ArtifactText
from onyx.tools.tool_implementations.sandbox.models import (
    FIND_LINE_MAX_CHARS,
    READ_LINE_MAX_CHARS,
    FindMatch,
)


def artifact_lines(text: ArtifactText) -> tuple[list[str], list[int]]:
    """The lines of `text`, numbered from 1, and the number of the first
    line of each page (none without pages). CRLF and a lone CR end lines too,
    each page starts a line, and a page's last newline ends its last line."""
    lines: list[str] = []
    page_starts: list[int] = []
    for page in text.pages:
        if text.paged:
            page_starts.append(len(lines) + 1)
        lines.extend(
            page.replace("\r\n", "\n")
            .replace("\r", "\n")
            .removesuffix("\n")
            .split("\n")
        )
    return lines, page_starts


def read_lines(
    lines: Sequence[str],
    page_starts: Sequence[int],
    first: int,
    last: int,
    max_chars: int,
) -> tuple[str, int]:
    """Lines `first` to `last` as `cat -n` prints them, with a
    `--- page N ---` line before the first line and before each page's first
    line. A line over READ_LINE_MAX_CHARS is cut, with a note. The text stops
    before a line that would take its JSON string past `max_chars`. Gives
    the text and the number of its last line (first - 1 when it has none)."""
    parts: list[str] = []
    used = 0
    end = first - 1
    for number in range(first, min(last, len(lines)) + 1):
        line = lines[number - 1]
        if len(line) > READ_LINE_MAX_CHARS:
            line = (
                f"{line[:READ_LINE_MAX_CHARS]}… "
                f"[{len(line) - READ_LINE_MAX_CHARS} more characters]"
            )
        part = f"{number:>6}\t{line}\n"
        page = bisect_right(page_starts, number)
        if page and (number == first or page_starts[page - 1] == number):
            part = f"--- page {page} ---\n{part}"
        # The characters of the part in a JSON string, without quotes.
        cost = len(json.dumps(part, ensure_ascii=False)) - 2
        if used + cost > max_chars:
            break
        parts.append(part)
        used += cost
        end = number
    return "".join(parts), end


def _cut_around(line: str, start: int, end: int) -> str:
    """At most FIND_LINE_MAX_CHARS of `line` around its characters `start`
    to `end`, with "…" where it is cut."""
    if len(line) <= FIND_LINE_MAX_CHARS:
        return line
    shown = max(
        0,
        min(
            start - max(FIND_LINE_MAX_CHARS - (end - start), 0) // 2,
            len(line) - FIND_LINE_MAX_CHARS,
        ),
    )
    return (
        ("…" if shown else "")
        + line[shown : shown + FIND_LINE_MAX_CHARS]
        + ("…" if shown + FIND_LINE_MAX_CHARS < len(line) else "")
    )


def find_lines(
    lines: Sequence[str],
    page_starts: Sequence[int],
    pattern: regex.Pattern[str],
    first: int,
    last: int,
    *,
    before: int,
    after: int,
    max_matches: int,
    offset: int,
    max_chars: int,
    timeout: float,
) -> tuple[list[FindMatch], int, int | None]:
    """The lines `first` to `last` in which `pattern` matches, as grep finds
    them: after the first `offset`, at most `max_matches`, each with `before`
    and `after` lines of context, while their JSON stays within `max_chars`.
    Matching stops after `timeout` seconds, also within a line (`regex`
    stops a pattern that backtracks without end). Gives the matches, the
    matching lines seen (the skipped and the unshown included), and the
    line where the time ran out (None: every line was searched)."""
    deadline = time.monotonic() + timeout
    matches: list[FindMatch] = []
    seen = 0
    used = 0
    full = False
    for number in range(first, min(last, len(lines)) + 1):
        line = lines[number - 1]
        remaining = deadline - time.monotonic()
        try:
            if remaining <= 0:
                raise TimeoutError
            found = pattern.search(line, concurrent=True, timeout=remaining)
        except TimeoutError:
            return matches, seen, number
        if found is None:
            continue
        seen += 1
        if seen <= offset or full:
            continue
        match = FindMatch(
            line=number,
            page=bisect_right(page_starts, number) or None,
            text=_cut_around(line, found.start(), found.end()),
            before=[
                _cut_around(context, 0, 0)
                for context in lines[max(number - 1 - before, 0) : number - 1]
            ],
            after=[
                _cut_around(context, 0, 0) for context in lines[number : number + after]
            ],
        )
        cost = len(match.model_dump_json()) + 1
        if len(matches) == max_matches or used + cost > max_chars:
            full = True
            continue
        matches.append(match)
        used += cost
    return matches, seen, None
