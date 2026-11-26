"""Parse and apply patches in the apply_patch patch format, and the string
replacements of the edit tool.

Pure functions, no I/O. Every `PatchError` message is model-facing.
"""

import re
from collections.abc import Callable, Hashable, Iterator

from pydantic import BaseModel, Field

BEGIN_PATCH_MARKER = "*** Begin Patch"
END_PATCH_MARKER = "*** End Patch"
ADD_FILE_MARKER = "*** Add File: "
DELETE_FILE_MARKER = "*** Delete File: "
UPDATE_FILE_MARKER = "*** Update File: "
MOVE_TO_MARKER = "*** Move to: "
EOF_MARKER = "*** End of File"
CHANGE_CONTEXT_MARKER = "@@ "
EMPTY_CHANGE_CONTEXT_MARKER = "@@"
SUMMARY_HEADER = "Success. Updated the following files:"

HUNK_HEADER_MARKERS = (ADD_FILE_MARKER, DELETE_FILE_MARKER, UPDATE_FILE_MARKER)
# Models often wrap the patch in a shell heredoc; the wrapper is stripped.
_HEREDOC_OPENERS = ("<<EOF", "<<'EOF'", '<<"EOF"')
_SOURCE_LINE_ENDING = re.compile(r"\r\n|\r|\n")
_DEFAULT_LINE_ENDING = "\n"
# Typographic punctuation folded to ASCII in the most lenient seek pass.
_PUNCTUATION_TO_ASCII = str.maketrans(
    {
        **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"),
        **dict.fromkeys("\u2018\u2019\u201a\u201b", "'"),
        **dict.fromkeys("\u201c\u201d\u201e\u201f", '"'),
        **dict.fromkeys(
            "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000",
            " ",
        ),
    }
)
_SEEK_PASSES: tuple[Callable[[str], str], ...] = (
    lambda line: line,
    str.rstrip,
    str.strip,
    lambda line: line.strip().translate(_PUNCTUATION_TO_ASCII),
)

# Largest input of a file tool call (a patch, the strings of an edit, or the
# contents of a write), in UTF-8 bytes.
FILE_TOOL_MAX_INPUT_BYTES = 1 << 20
# Largest file that the file tools read to update it, and that an edit makes.
FILE_TOOL_MAX_FILE_BYTES = 10 << 20
# Largest total of updated file contents that one patch holds before it
# writes: the server keeps them in memory.
APPLY_PATCH_MAX_STAGED_BYTES = 32 << 20
# Most lines of a file that an update reads.
MAX_UPDATE_LINES = 500_000
# Most source lines that the searches of one patch read (all hunks, all
# passes): a patch of many hunks must not hold an API thread.
MAX_SEEK_LINES = 50_000_000

# (start index in the source lines, number of source lines replaced, new lines)
Replacement = tuple[int, int, list[str]]


class PatchError(Exception):
    """A patch or edit that cannot be parsed or applied. The message is
    model-facing."""


class SeekBudget:
    """The source lines that one patch's searches may still read. `check`
    runs before each search, such as a cancellation check."""

    def __init__(self, check: Callable[[], None] = lambda: None) -> None:
        self.remaining = MAX_SEEK_LINES
        self._check = check

    def spend(self, lines: int) -> None:
        self._check()
        self.remaining -= lines
        if self.remaining < 0:
            raise PatchError(
                "the patch is too large to verify; split it into smaller patches"
            )


class UpdateChunk(BaseModel):
    # One line (usually a class or function signature) that must occur before old_lines.
    change_context: str | None = None
    # A contiguous block of source lines that new_lines replaces.
    old_lines: list[str] = Field(default_factory=list)
    new_lines: list[str] = Field(default_factory=list)
    # (old_lines index, new_lines index) pairs of lines written as context (" " prefix).
    # Matched source lines at these positions are kept verbatim.
    context_line_indices: list[tuple[int, int]] = Field(default_factory=list)
    # old_lines must match at the end of the file.
    is_end_of_file: bool = False


class AddFile(BaseModel):
    path: str
    contents: str


class DeleteFile(BaseModel):
    path: str


class UpdateFile(BaseModel):
    path: str
    move_path: str | None
    chunks: list[UpdateChunk]


PatchHunk = AddFile | DeleteFile | UpdateFile


def _invalid_patch(message: str) -> PatchError:
    return PatchError(f"invalid patch: {message}")


def _invalid_hunk(message: str, line_number: int) -> PatchError:
    return PatchError(f"invalid hunk at line {line_number}, {message}")


def _invalid_hunk_header(trimmed_line: str, line_number: int) -> PatchError:
    return _invalid_hunk(
        f"'{trimmed_line}' is not a valid hunk header. Valid hunk headers: "
        "'*** Add File: {path}', '*** Delete File: {path}', '*** Update File: {path}'",
        line_number,
    )


def _unexpected_update_line(line: str, line_number: int) -> PatchError:
    return _invalid_hunk(
        f"Unexpected line found in update hunk: '{line}'. Every line should start with "
        "' ' (context line), '+' (added line), or '-' (removed line)",
        line_number,
    )


def _envelope_error(lines: list[str]) -> PatchError | None:
    first_line = lines[0].strip() if lines else None
    last_line = lines[-1].strip() if lines else None
    if first_line == BEGIN_PATCH_MARKER and last_line == END_PATCH_MARKER:
        return None
    if first_line is not None and first_line != BEGIN_PATCH_MARKER:
        return _invalid_patch("The first line of the patch must be '*** Begin Patch'")
    return _invalid_patch("The last line of the patch must be '*** End Patch'")


def _next_hunk_boundary(
    lines: list[str], start: int, stop: int, normalize: Callable[[str], str]
) -> int:
    return next(
        (
            index
            for index in range(start, stop)
            if normalize(lines[index]) == END_PATCH_MARKER
            or normalize(lines[index]).startswith(HUNK_HEADER_MARKERS)
        ),
        stop,
    )


def _is_empty_chunk(chunk: UpdateChunk) -> bool:
    return not chunk.old_lines and not chunk.new_lines


def _parse_update_file(
    path: str,
    header_line_number: int,
    body: list[str],
    closing_line: str,
) -> UpdateFile:
    """Parse the lines after `*** Update File:` up to the next hunk boundary.

    `closing_line` is that boundary (a hunk header or `*** End Patch`); it
    directly follows the body.
    """
    move_path: str | None = None
    chunks: list[UpdateChunk] = []
    for offset, line in enumerate(body):
        line_number = header_line_number + 1 + offset
        update_line = line.rstrip()
        last_chunk = chunks[-1] if chunks else None
        is_context_marker = (
            update_line == EMPTY_CHANGE_CONTEXT_MARKER
            or update_line.startswith(CHANGE_CONTEXT_MARKER)
        )

        if last_chunk is not None and last_chunk.is_end_of_file:
            if not update_line:
                continue
            if not is_context_marker:
                raise _invalid_hunk(
                    f"Expected update hunk to start with a @@ context marker, got: '{line}'",
                    line_number,
                )

        if (
            last_chunk is None
            and move_path is None
            and update_line.startswith(MOVE_TO_MARKER)
        ):
            move_path = update_line.removeprefix(MOVE_TO_MARKER)
            continue

        if is_context_marker:
            if last_chunk is not None and _is_empty_chunk(last_chunk):
                raise _unexpected_update_line(line, line_number)
            change_context = (
                None
                if update_line == EMPTY_CHANGE_CONTEXT_MARKER
                else update_line.removeprefix(CHANGE_CONTEXT_MARKER)
            )
            chunks.append(UpdateChunk(change_context=change_context))
            continue

        if update_line == EOF_MARKER:
            if last_chunk is not None:
                if _is_empty_chunk(last_chunk):
                    raise _invalid_hunk(
                        "Update hunk does not contain any lines", line_number
                    )
                last_chunk.is_end_of_file = True
            continue

        # A bare empty line is an empty context line.
        if not line or line[0] in " +-":
            if last_chunk is None:
                last_chunk = UpdateChunk()
                chunks.append(last_chunk)
            marker, content = line[:1], line[1:]
            if marker == "+":
                last_chunk.new_lines.append(content)
            elif marker == "-":
                last_chunk.old_lines.append(content)
            else:
                last_chunk.context_line_indices.append(
                    (len(last_chunk.old_lines), len(last_chunk.new_lines))
                )
                last_chunk.old_lines.append(content)
                last_chunk.new_lines.append(content)
            continue

        if last_chunk is not None and not _is_empty_chunk(last_chunk):
            raise _invalid_hunk(
                f"Expected update hunk to start with a @@ context marker, got: '{line}'",
                line_number,
            )
        raise _unexpected_update_line(line, line_number)

    closing_line_number = header_line_number + 1 + len(body)
    if not chunks:
        raise _invalid_hunk(
            f"Update file hunk for path '{path}' is empty", header_line_number
        )
    if _is_empty_chunk(chunks[-1]):
        if closing_line == END_PATCH_MARKER:
            raise _invalid_hunk(
                "Update hunk does not contain any lines", closing_line_number
            )
        raise _unexpected_update_line(closing_line, closing_line_number)
    return UpdateFile(path=path, move_path=move_path, chunks=chunks)


def ensure_unique_targets(
    hunks: list[PatchHunk], file_key: Callable[[str], Hashable]
) -> None:
    """Reject patches where two operations (or a move's source and
    destination) change one file. `file_key` gives two paths of one file
    the same key."""
    seen: set[Hashable] = set()
    for hunk in hunks:
        for path in (
            hunk.path,
            hunk.move_path if isinstance(hunk, UpdateFile) else None,
        ):
            if path is None:
                continue
            key = file_key(path)
            if key in seen:
                raise PatchError(f"multiple operations target {path}")
            seen.add(key)


def parse_patch(text: str) -> list[PatchHunk]:
    """Parse patch text into hunks. Paths stay as spelled in the patch."""
    stripped = text.strip()
    lines = (
        [line.removesuffix("\r") for line in stripped.split("\n")] if stripped else []
    )
    error = _envelope_error(lines)
    if error is not None:
        # Lenient: a heredoc wrapper around the envelope.
        if not (
            len(lines) >= 4
            and lines[0] in _HEREDOC_OPENERS
            and lines[-1].endswith("EOF")
        ):
            raise error
        lines = lines[1:-1]
        inner_error = _envelope_error(lines)
        if inner_error is not None:
            raise inner_error
    # lines[0] is `*** Begin Patch` and lines[-1] is `*** End Patch`.
    end_index = len(lines) - 1
    hunks: list[PatchHunk] = []
    index = 1
    while index < end_index:
        line_number = index + 1
        trimmed = lines[index].strip()
        if trimmed == END_PATCH_MARKER:
            if any(line.strip() for line in lines[index + 1 : end_index]):
                raise _invalid_patch(
                    "The last line of the patch must be '*** End Patch'"
                )
            break
        if trimmed.startswith(ADD_FILE_MARKER):
            body_end = _next_hunk_boundary(lines, index + 1, end_index, str.strip)
            contents: list[str] = []
            for body_index in range(index + 1, body_end):
                body_line = lines[body_index]
                if not body_line.startswith("+"):
                    raise _invalid_hunk_header(body_line.strip(), body_index + 1)
                contents.append(body_line[1:] + "\n")
            hunks.append(
                AddFile(
                    path=trimmed.removeprefix(ADD_FILE_MARKER),
                    contents="".join(contents),
                )
            )
        elif trimmed.startswith(DELETE_FILE_MARKER):
            body_end = _next_hunk_boundary(lines, index + 1, end_index, str.strip)
            if body_end > index + 1:
                raise _invalid_hunk_header(lines[index + 1].strip(), line_number + 1)
            hunks.append(DeleteFile(path=trimmed.removeprefix(DELETE_FILE_MARKER)))
        elif trimmed.startswith(UPDATE_FILE_MARKER):
            # Inside an update hunk, only unindented markers end the hunk; an
            # indented marker is a context line.
            body_end = _next_hunk_boundary(lines, index + 1, end_index, str.rstrip)
            hunks.append(
                _parse_update_file(
                    trimmed.removeprefix(UPDATE_FILE_MARKER),
                    line_number,
                    lines[index + 1 : body_end],
                    lines[body_end].rstrip()
                    if body_end < end_index
                    else END_PATCH_MARKER,
                )
            )
        else:
            raise _invalid_hunk_header(trimmed, line_number)
        index = body_end

    if not hunks:
        raise PatchError("No files were modified.")
    return hunks


def _seek_sequence(
    lines: list[str], pattern: list[str], start: int, eof: bool, budget: SeekBudget
) -> int | None:
    """Return the first index >= `start` where `pattern` occurs in `lines`, or None.

    Passes go from strict to lenient: exact, trailing whitespace ignored, surrounding
    whitespace ignored, then typographic punctuation folded to ASCII. With `eof`, the
    search starts where the pattern would end the file. Each pass is a
    Knuth-Morris-Pratt scan: linear in the lines it reads, whatever repeats.
    """
    if not pattern:
        # An end-of-file chunk keeps its place even with nothing to match.
        return len(lines) if eof else start
    if len(pattern) > len(lines):
        return None
    search_start = max(len(lines) - len(pattern), start) if eof else start
    for normalize in _SEEK_PASSES:
        budget.spend(len(lines) - search_start)
        wanted = [normalize(line) for line in pattern]
        # fallback[i]: the longest proper prefix of wanted[: i + 1] that is
        # also its suffix.
        fallback = [0] * len(wanted)
        matched = 0
        for index in range(1, len(wanted)):
            while matched and wanted[index] != wanted[matched]:
                matched = fallback[matched - 1]
            if wanted[index] == wanted[matched]:
                matched += 1
            fallback[index] = matched
        matched = 0
        for index in range(search_start, len(lines)):
            line = normalize(lines[index])
            while matched and line != wanted[matched]:
                matched = fallback[matched - 1]
            if line == wanted[matched]:
                matched += 1
                if matched == len(wanted):
                    return index - len(wanted) + 1
    return None


def _compute_replacements(
    original_lines: list[str],
    path: str,
    chunks: list[UpdateChunk],
    budget: SeekBudget,
) -> list[Replacement]:
    replacements: list[Replacement] = []
    line_index = 0
    for chunk in chunks:
        if chunk.change_context is not None:
            context_index = _seek_sequence(
                original_lines, [chunk.change_context], line_index, False, budget
            )
            if context_index is None:
                raise PatchError(
                    f"Failed to find context '{chunk.change_context}' in {path}"
                )
            line_index = context_index + 1

        if not chunk.old_lines:
            # A pure addition goes right after its @@ context line, else at the end.
            insert_index = (
                line_index
                if chunk.change_context is not None and not chunk.is_end_of_file
                else len(original_lines)
            )
            replacements.append((insert_index, 0, chunk.new_lines))
            continue

        pattern = chunk.old_lines
        new_lines = chunk.new_lines
        found = _seek_sequence(
            original_lines, pattern, line_index, chunk.is_end_of_file, budget
        )
        # A trailing empty old line usually stands for the file's final newline,
        # which the source lines do not hold as an extra element.
        if found is None and pattern[-1] == "":
            pattern = pattern[:-1]
            if new_lines and new_lines[-1] == "":
                new_lines = new_lines[:-1]
            found = _seek_sequence(
                original_lines, pattern, line_index, chunk.is_end_of_file, budget
            )
        if found is None:
            raise PatchError(
                f"Failed to find expected lines in {path}:\n"
                + "\n".join(chunk.old_lines)
            )

        # Keep matched context lines from the source so their exact text and
        # line endings survive; replace only the runs between them.
        old_start = 0
        new_start = 0
        for old_context, new_context in chunk.context_line_indices:
            if old_context >= len(pattern) or new_context >= len(new_lines):
                break
            if old_start != old_context or new_start != new_context:
                replacements.append(
                    (
                        found + old_start,
                        old_context - old_start,
                        new_lines[new_start:new_context],
                    )
                )
            old_start = old_context + 1
            new_start = new_context + 1
        if old_start != len(pattern) or new_start != len(new_lines):
            replacements.append(
                (found + old_start, len(pattern) - old_start, new_lines[new_start:])
            )
        line_index = found + len(pattern)

    # Stable sort: an insertion keeps its place before a replacement at the same index.
    replacements.sort(key=lambda replacement: replacement[0])
    return replacements


def update_contents(
    path: str,
    original: str,
    chunks: list[UpdateChunk],
    budget: SeekBudget | None = None,
) -> str:
    """Apply update chunks to `original`. `path` appears only in error messages.
    `budget` spans the files of one patch (default: a new one).

    Unchanged lines keep their line endings. New lines use the first line ending
    in the file (LF if none), and every line of the result ends with one.
    """
    # Each line is a few records: bound them before any is made.
    line_endings = original.count("\n") + original.count("\r") - original.count("\r\n")
    if line_endings > MAX_UPDATE_LINES:
        raise PatchError(
            f"Failed to update {path}: it has more than {MAX_UPDATE_LINES} lines; "
            "edit it with exec_command"
        )
    source_lines: list[tuple[str, str | None]] = []
    line_start = 0
    for match in _SOURCE_LINE_ENDING.finditer(original):
        source_lines.append((original[line_start : match.start()], match.group()))
        line_start = match.end()
    if line_start < len(original):
        source_lines.append((original[line_start:], None))
    first_ending = next(
        (ending for _, ending in source_lines if ending is not None),
        _DEFAULT_LINE_ENDING,
    )

    replacements = _compute_replacements(
        [text for text, _ in source_lines], path, chunks, budget or SeekBudget()
    )

    output: list[str] = []
    source_index = 0
    for start, old_length, new_lines in replacements:
        output.extend(
            text + (ending or first_ending)
            for text, ending in source_lines[source_index:start]
        )
        output.extend(line + first_ending for line in new_lines)
        source_index = start + old_length
    output.extend(
        text + (ending or first_ending) for text, ending in source_lines[source_index:]
    )
    return "".join(output)


def display_patch(path: str, old: str | None, new: str) -> str:
    """A patch that shows an edit or a write of `path`: an added file of `new`
    when `old` is None, else an update of `old` lines to `new` lines."""

    def lines(prefix: str, text: str) -> list[str]:
        return (
            [prefix + line for line in text.removesuffix("\n").split("\n")]
            if text
            else []
        )

    body = (
        [ADD_FILE_MARKER + path, *lines("+", new)]
        if old is None
        else [
            UPDATE_FILE_MARKER + path,
            EMPTY_CHANGE_CONTEXT_MARKER,
            *lines("-", old),
            *lines("+", new),
        ]
    )
    return "\n".join([BEGIN_PATCH_MARKER, *body, END_PATCH_MARKER])


def summarize(hunks: list[PatchHunk]) -> str:
    """The success text: added, then modified (a move lists its destination), then deleted."""
    added = [f"A {hunk.path}\n" for hunk in hunks if isinstance(hunk, AddFile)]
    modified = [
        f"M {hunk.move_path or hunk.path}\n"
        for hunk in hunks
        if isinstance(hunk, UpdateFile)
    ]
    deleted = [f"D {hunk.path}\n" for hunk in hunks if isinstance(hunk, DeleteFile)]
    return SUMMARY_HEADER + "\n" + "".join(added + modified + deleted)


def edit_text(original: str | None, old: str, new: str, replace_all: bool) -> str:
    """The contents of a file after the edit tool replaces `old` with `new`.
    `original` is None for a missing file; an empty `old` creates a file, or
    fills an empty one, with `new`.

    The match is exact text; only line breaks may differ (CRLF, CR or LF).
    Unchanged text keeps its line breaks, and `new` gets the file's first one
    (LF if none), as an apply_patch update does.
    """
    if old == new:
        raise PatchError(
            "No changes to make: old_string and new_string are exactly the same."
        )
    if original is None:
        if old:
            raise PatchError("File does not exist.")
        return new
    if not old:
        if original.strip():
            raise PatchError("Cannot create new file - file already exists.")
        return new
    # Search a copy with LF for every line break, where a CRLF is one
    # character, and map each match back to `original`. str.find keeps the
    # search linear in the size of the file.
    text = _SOURCE_LINE_ENDING.sub("\n", original)
    target = _SOURCE_LINE_ENDING.sub("\n", old)
    # Removing whole lines also removes the last one's line break.
    takes_line_break = not new and not target.endswith("\n")

    def matches() -> Iterator[tuple[int, int]]:
        """The span in `original` of each match, left to right, without overlaps."""
        # The index in `text` of each CRLF.
        crlf_indexes = (
            crlf.start() - crlfs_before
            for crlfs_before, crlf in enumerate(re.finditer("\r\n", original))
        )
        next_crlf = next(crlf_indexes, None)
        crlfs_before = 0

        def original_index(index: int) -> int:
            nonlocal next_crlf, crlfs_before
            while next_crlf is not None and next_crlf < index:
                crlfs_before += 1
                next_crlf = next(crlf_indexes, None)
            return index + crlfs_before

        start = text.find(target)
        while start != -1:
            end = start + len(target)
            if (
                takes_line_break
                and text.startswith("\n", end)
                and (start == 0 or text[start - 1] == "\n")
            ):
                end += 1
            yield original_index(start), original_index(end)
            start = text.find(target, end)

    first_break = _SOURCE_LINE_ENDING.search(original)
    replacement = _SOURCE_LINE_ENDING.sub(
        first_break.group() if first_break else _DEFAULT_LINE_ENDING, new
    )
    count = 0
    removed_bytes = 0
    for start, end in matches():
        count += 1
        removed_bytes += len(original[start:end].encode())
    if not count:
        raise PatchError(f"String to replace not found in file.\nString: {old}")
    if count > 1 and not replace_all:
        raise PatchError(
            f"Found {count} matches of the string to replace, but "
            "replace_all is false. To replace all occurrences, set replace_all "
            "to true. To replace only one occurrence, please provide more "
            f"context to uniquely identify the instance.\nString: {old}"
        )
    size = len(original.encode()) - removed_bytes + count * len(replacement.encode())
    if size > FILE_TOOL_MAX_FILE_BYTES:
        raise PatchError(
            f"The edit would make the file {size} bytes, larger than "
            f"{FILE_TOOL_MAX_FILE_BYTES} bytes; make a smaller edit"
        )
    pieces: list[str] = []
    kept_from = 0
    for start, end in matches():
        pieces += (original[kept_from:start], replacement)
        kept_from = end
    pieces.append(original[kept_from:])
    return "".join(pieces)
