"""Pull request diffs cut into the windows Jev screens.

A window is a contiguous run of one hunk. CI cuts windows from the PR's file
patches. Eval cuts them from the diff at each review comment's commit with the
same `cut_windows`, so eval scores exactly what CI would screen.
"""

import hashlib
import re
from dataclasses import dataclass

__all__ = [
    "Added",
    "Context",
    "DiffLine",
    "FilePatch",
    "Hunk",
    "PullRequest",
    "Removed",
    "Window",
    "cut_windows",
    "parse_hunks",
]

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
_BLOCK_OPENERS: tuple[str, ...] = (":", "{", "(")


@dataclass(frozen=True)
class Added:
    new_line: int
    text: str


@dataclass(frozen=True)
class Removed:
    old_line: int
    text: str


@dataclass(frozen=True)
class Context:
    old_line: int
    new_line: int
    text: str


type DiffLine = Added | Removed | Context


def _prefix(line: DiffLine) -> str:
    match line:
        case Added():
            return "+"
        case Removed():
            return "-"
        case Context():
            return " "


@dataclass(frozen=True)
class Hunk:
    header: str
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True)
class Window:
    """At most `max_lines` lines of one hunk, with at least one Added line.

    `cut_windows` is the only producer. The id and the rendered text leave out
    line numbers, so the same code at another commit is the same window.
    """

    path: str
    hunk_header: str
    lines: tuple[DiffLine, ...]

    @property
    def anchor_lines(self) -> tuple[int, ...]:
        return tuple(line.new_line for line in self.lines if isinstance(line, Added))

    @property
    def first_new_line(self) -> int:
        return min(self._new_lines())

    @property
    def last_new_line(self) -> int:
        return max(self._new_lines())

    @property
    def id(self) -> str:
        return hashlib.sha256(f"{self.path}\n{self.render()}".encode()).hexdigest()

    def covers_new_line(self, line: int) -> bool:
        return self.first_new_line <= line <= self.last_new_line

    def render(self) -> str:
        """The diff text Jev reads."""
        body = [f"{_prefix(line)}{line.text}" for line in self.lines]
        header = [f"@@ {self.hunk_header}"] if self.hunk_header else []
        return "\n".join(header + body)

    def render_numbered(self) -> str:
        """The diff text the LLM reads, with the new-side line number of each line."""
        rows: list[str] = []
        for line in self.lines:
            number = "" if isinstance(line, Removed) else str(line.new_line)
            rows.append(f"{number:>6} {_prefix(line)}{line.text}")
        return "\n".join(rows)

    def _new_lines(self) -> list[int]:
        return [line.new_line for line in self.lines if not isinstance(line, Removed)]


def parse_hunks(patch: str) -> list[Hunk]:
    """Parse the `@@` hunks of one file's unified diff, as GitHub returns it."""
    hunks: list[Hunk] = []
    header = ""
    lines: list[DiffLine] = []
    old_line = new_line = 0
    started = False
    for raw in patch.split("\n"):
        if match := _HUNK_HEADER.match(raw):
            if started:
                hunks.append(Hunk(header, tuple(lines)))
            started = True
            old_line, new_line = int(match.group(1)), int(match.group(2))
            header, lines = match.group(3).strip(), []
            continue
        if not started or raw.startswith("\\"):
            continue
        marker, text = raw[:1], raw[1:]
        if marker == "+":
            lines.append(Added(new_line, text))
            new_line += 1
        elif marker == "-":
            lines.append(Removed(old_line, text))
            old_line += 1
        elif marker == " " or raw == "":
            lines.append(Context(old_line, new_line, text))
            old_line += 1
            new_line += 1
        else:
            raise ValueError(f"not a unified diff line: {raw[:80]!r}")
    if started:
        hunks.append(Hunk(header, tuple(lines)))
    elif patch.strip():
        raise ValueError("patch has no @@ hunk header")
    return [_trim_trailing_blank(hunk) for hunk in hunks]


def _trim_trailing_blank(hunk: Hunk) -> Hunk:
    # A patch that ends with "\n" splits into a final empty string, which is not
    # a context line.
    lines = hunk.lines
    while lines and isinstance(lines[-1], Context) and lines[-1].text == "":
        lines = lines[:-1]
    return Hunk(hunk.header, lines)


def cut_windows(path: str, patch: str, max_lines: int) -> list[Window]:
    """Every window of one file patch, in line order."""
    windows: list[Window] = []
    for hunk in parse_hunks(patch):
        start = 0
        while start < len(hunk.lines):
            end = _cut_point(hunk.lines, start, max_lines)
            piece = hunk.lines[start:end]
            if any(isinstance(line, Added) for line in piece):
                windows.append(Window(path, hunk.header, piece))
            start = end
    return windows


def _cut_point(lines: tuple[DiffLine, ...], start: int, max_lines: int) -> int:
    """The end (exclusive) of the window that starts at `start`.

    Prefers the last blank line or dedent in the second half of the window, and
    never ends a window right after a block opener, so a header keeps its body.
    """
    limit = start + max_lines
    if limit >= len(lines):
        return len(lines)
    allowed = [
        end for end in range(start + 1, limit + 1) if not _opens_block(lines[end - 1])
    ]
    preferred = [
        end
        for end in allowed
        if end - start >= max_lines // 2 and _is_boundary(lines[end - 1], lines[end])
    ]
    if preferred:
        return preferred[-1]
    if allowed:
        return allowed[-1]
    return limit


def _opens_block(line: DiffLine) -> bool:
    return line.text.rstrip().endswith(_BLOCK_OPENERS)


def _is_boundary(last: DiffLine, following: DiffLine) -> bool:
    if not last.text.strip():
        return True
    return bool(following.text.strip()) and _indent(following) < _indent(last)


def _indent(line: DiffLine) -> int:
    return len(line.text) - len(line.text.lstrip())


@dataclass(frozen=True)
class FilePatch:
    path: str
    # None when GitHub omits the patch (binary or too large).
    patch: str | None


@dataclass(frozen=True)
class PullRequest:
    repo: str
    number: int
    # The tree the repo search reads. Code there predates the PR.
    base_sha: str
    head_sha: str
    files: tuple[FilePatch, ...]

    def windows(self, max_lines: int) -> list[Window]:
        return [
            window
            for file in sorted(self.files, key=lambda file: file.path)
            if file.patch is not None
            for window in cut_windows(file.path, file.patch, max_lines)
        ]

    def patch_for(self, path: str) -> str:
        return next((file.patch or "" for file in self.files if file.path == path), "")
