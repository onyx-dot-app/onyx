"""Large tool results in a chat with a sandbox (`spill_large_result`, the chat
agent's prepare_tool_result hook). A result goes to a file in the user's VM,
and the model, the live events and the saved history get a bounded view with
the file's path:

- A result with a full value (`ToolResult.full_value`): the tool cut its
  content itself, so it always spills. The file holds the full value, and
  the model gets the content with a note.
- Any other result over the limits: the file holds its content, and the model
  gets a preview.
"""

import json
import re
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import NamedTuple

from pydantic_core import to_json

from onyx.agents.models import ToolResultContext
from onyx.llm.cancellation import current_cancellation, wait_for_future
from onyx.llm.models import ToolResult
from onyx.microvm.models import FileListing, FileType
from onyx.server.features.build.sandbox.harness_base import (
    TOOL_RESULTS_ROOT,
    HarnessSandbox,
    session_tool_results,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.tools.constants import (
    CITEABLE_TOOLS_NAMES,
    CODE_MODE_TOOL_NAME,
    FILE_READER_TOOL_NAME,
    SKILLS_READ_TOOL_NAME,
    WAIT_CODE_TOOL_NAME,
)
from onyx.tools.models import CustomToolCallSummary, SearchResults
from onyx.tools.tool_implementations.code_mode.models import CodeModeExecutionResult
from onyx.tools.tool_implementations.sandbox.models import (
    SandboxExecResult,
    SpilledOutput,
)
from onyx.tools.tool_implementations.sandbox.sandbox_tools import (
    ExecCommandTool,
    LibraryListTool,
    WriteStdinTool,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.utils import truncation_marker
from onyx.tools.tool_implementations.web_search.utils import (
    truncate_search_result_content,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()

# Sizes are in characters, which cost nothing to measure. They do not bound
# tokens: text such as CJK takes about one token for each character.
RESULT_MAX_CHARS = 50_000
# All results of one step; a result that arrives after the budget is used up
# spills even when it is under the limit of one result.
STEP_MAX_CHARS = 200_000
PREVIEW_HEAD_CHARS = 2_000
PREVIEW_TAIL_CHARS = 1_000
# A result without a full value spills only when its preview leaves out more
# than this.
SPILL_MIN_DROPPED_CHARS = PREVIEW_HEAD_CHARS + PREVIEW_TAIL_CHARS
# The most that one file holds; the rest is cut on a character boundary.
SPILL_MAX_BYTES = 64 << 20
# The most that all files under TOOL_RESULTS_ROOT hold, for every chat of the
# VM (its /tmp is memory): after each write, the oldest files go until the
# rest fit.
TOOL_RESULTS_MAX_BYTES = 512 << 20
# The most entries that the eviction lists: the guest daemon's maximum.
LIST_MAX_ENTRIES = 100_000
# How long a result waits for its write; then the model gets the failure view.
# A spill holds up to SPILL_MAX_BYTES of encoded bytes in memory until its
# write ends, up to this long after a Stop or a timed-out wait.
SPILL_WRITE_TIMEOUT_SECONDS = 30.0
# A page's title or URL in the list of spilled pages keeps at most this much.
PAGE_LIST_FIELD_MAX_CHARS = 300
# Characters that the write encodes at a time.
_ENCODE_CHARS = 1 << 20
# The modification time of a listed file that has none: it goes last.
_UNKNOWN_AGE = datetime.max.replace(tzinfo=timezone.utc)
# Tools whose content the limits of one result and one step do not cut: they
# cut it themselves (the code mode cells, exec), page through it (read_file,
# skills_read and library_list, whose page keeps within
# ARTIFACTS_LIST_MAX_CHARS, so a spill would only be read back), or the model
# cites it whole. A full value still spills.
_OWN_LIMITS = frozenset(
    {
        CODE_MODE_TOOL_NAME,
        WAIT_CODE_TOOL_NAME,
        ExecCommandTool.NAME,
        WriteStdinTool.NAME,
        FILE_READER_TOOL_NAME,
        SKILLS_READ_TOOL_NAME,
        LibraryListTool.NAME,
        *CITEABLE_TOOLS_NAMES,
    }
)
_UNSAFE_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_.-]")
_CLOSING_TAG = re.compile(r"</(persisted-output)", re.IGNORECASE)
SPILL_FAILED_NOTE = (
    "[The sandbox could not save the full output, so this is only part of it.]"
)
FULL_VALUE_NOTE = "The output above is cut. The file holds all of it."


class _Saved(NamedTuple):
    path: str
    # The bytes in the file.
    size: int
    # SPILL_MAX_BYTES cut the data; the file holds its start.
    cut: bool


def _utf8_parts(text: str) -> tuple[list[bytes], bool]:
    """The UTF-8 bytes of `text` in parts, at most SPILL_MAX_BYTES of them
    cut on a character boundary, and whether the cut left any out. No part
    holds the whole text. A lone surrogate becomes "?"."""
    parts: list[bytes] = []
    size = 0
    for start in range(0, len(text), _ENCODE_CHARS):
        part = text[start : start + _ENCODE_CHARS].encode(errors="replace")
        if size + len(part) > SPILL_MAX_BYTES:
            end = SPILL_MAX_BYTES - size
            # A UTF-8 character has at most 3 continuation bytes (10xxxxxx);
            # the cut moves back to the start of the character that it splits.
            while end > 0 and part[end] & 0xC0 == 0x80:
                end -= 1
            parts.append(part[:end])
            return parts, True
        parts.append(part)
        size += len(part)
    return parts, False


def _evict(sandbox: HarnessSandbox, ref: HarnessSandboxRef, written: str) -> None:
    """Delete the oldest files under TOOL_RESULTS_ROOT, of any chat, while
    all of them hold more than TOOL_RESULTS_MAX_BYTES. `written` stays."""

    def oldest(listing: FileListing) -> list[str]:
        limit = TOOL_RESULTS_MAX_BYTES
        if listing.truncated:
            # Files past the listing hold bytes too.
            logger.warning("tool_result_spill_listing_truncated path=%s", written)
            limit //= 2
        files = [entry for entry in listing.entries if entry.type is FileType.REGULAR]
        total = sum(entry.size for entry in files)
        deleted: list[str] = []
        for entry in sorted(files, key=lambda entry: entry.modified_at or _UNKNOWN_AGE):
            if total <= limit:
                break
            if entry.path != written:
                deleted.append(entry.path)
                total -= entry.size
        return deleted

    sandbox.delete_listed_files(
        ref, TOOL_RESULTS_ROOT, oldest, max_entries=LIST_MAX_ENTRIES
    )


def _save(
    turn: SandboxTurn, context: ToolResultContext, parts: list[bytes], cut: bool
) -> _Saved:
    """Write `parts` to the call's file in the chat's directory of the VM,
    then, without the caller, evict old files (`_evict`). The write wakes the
    VM if needed. It does not start after a Stop, and the caller waits at
    most SPILL_WRITE_TIMEOUT_SECONDS for it, and not past a Stop; then, or
    when the write fails, it raises. Writing a call's result again replaces
    its file; an amendment writes its own file."""
    signal = current_cancellation()
    if signal is not None:
        signal.check()
    # Call IDs are unique only within one conversation, so the step's
    # message ID leads.
    name = _UNSAFE_NAME_CHARACTERS.sub(
        "_",
        f"{context.message_id}_{context.calls[0].id}"
        + ("_amended" if context.amended else ""),
    )
    ref = turn.start_call()
    sandbox = turn.sandbox
    path = f"{session_tool_results(ref.session_id)}/{name}.txt"
    written: Future[None] = Future()

    def write_then_evict() -> None:
        try:
            sandbox.write_file(
                ref, path, parts, timeout_seconds=SPILL_WRITE_TIMEOUT_SECONDS
            )
        except BaseException as error:
            written.set_exception(error)
            return
        written.set_result(None)
        try:
            _evict(sandbox, ref, path)
        except Exception:
            # The next write tries again; the files go when the VM stops.
            logger.exception("tool_result_spill_evict_failed path=%s", path)

    start_thread_future(write_then_evict, name="tool-result-spill")
    # After a Stop or a timeout, the write ends at its own timeout.
    wait_for_future(written, SPILL_WRITE_TIMEOUT_SECONDS, signal)
    return _Saved(path=path, size=sum(map(len, parts)), cut=cut)


def _envelope(saved: _Saved, body: str, *, code_mode: bool) -> str:
    """The note that names a spilled result's file: `body`, which cannot
    close the tag, and how to read the file."""
    exec_call = (
        f"{ExecCommandTool.NAME} in an {CODE_MODE_TOOL_NAME} program"
        if code_mode
        else ExecCommandTool.NAME
    )
    return (
        f'<persisted-output path="{saved.path}" bytes={saved.size}>\n'
        # JSON reads `\/` as `/`.
        + _CLOSING_TAG.sub(r"<\\/\1", body)
        + (f"\nOnly the first {saved.size:,} bytes are saved." if saved.cut else "")
        + f"\nRead the file with {exec_call} (grep, sed, head, tail). It "
        "lasts while the sandbox runs. If it is missing, the sandbox restarted "
        "or newer results replaced it: call the tool again only if the call is "
        "read-only.\n</persisted-output>"
    )


def _head_and_tail(text: str) -> tuple[str, str]:
    """The preview's head and tail of `text`; they do not overlap."""
    head = text[:PREVIEW_HEAD_CHARS]
    return head, text[max(len(head), len(text) - PREVIEW_TAIL_CHARS) :]


def spill_large_result(
    turn: SandboxTurn, context: ToolResultContext, *, code_mode: bool
) -> ToolResult:
    """The result, or, when it is too large, a bounded view and the path of
    the file in the VM that holds the rest. When the write fails or times
    out, the model gets the bounded view with SPILL_FAILED_NOTE."""
    result = context.result
    full = result.full_value
    if isinstance(full, SandboxExecResult):
        return _spill_full_text(turn, context, full.output, code_mode=code_mode)
    if isinstance(full, str):
        return _spill_full_text(turn, context, full, code_mode=code_mode)
    if isinstance(full, SearchResults):
        return _spill_pages(turn, context, full, code_mode=code_mode)
    text = result.content
    if (
        context.calls[0].name in _OWN_LIMITS
        or len(text) - (PREVIEW_HEAD_CHARS + PREVIEW_TAIL_CHARS)
        <= SPILL_MIN_DROPPED_CHARS
    ):
        return result
    step_chars = sum(len(recorded.content) for recorded in context.step_results)
    if len(text) <= RESULT_MAX_CHARS and step_chars + len(text) <= STEP_MAX_CHARS:
        return result

    head, tail = _head_and_tail(text)
    spilled: SpilledOutput | None = None
    try:
        saved = _save(turn, context, *_utf8_parts(text))
    except Exception:
        logger.exception("tool_result_spill_failed call=%s", context.calls[0].id)
        content = (
            head
            + truncation_marker(len(text) - len(head) - len(tail))
            + tail
            + f"\n{SPILL_FAILED_NOTE}"
        )
    else:
        content = _envelope(
            saved,
            f"Preview (first {PREVIEW_HEAD_CHARS:,} characters):\n{head}\n"
            f"Preview (last {PREVIEW_TAIL_CHARS:,} characters):\n{tail}\n"
            "The file holds the whole output.",
            code_mode=code_mode,
        )
        spilled = SpilledOutput(head=head, tail=tail)
    # A custom or MCP tool's output in the details becomes the preview, so the
    # saved history does not hold the text that the model did not get. Python
    # details keep their own bounded output.
    details = result.details
    if isinstance(details, CustomToolCallSummary) and details.copies_output:
        details = details.model_copy(
            update={
                "tool_result": None if spilled is not None else content,
                "structured_result": None,
                "spilled": spilled,
            }
        )
    elif details is None and spilled is not None:
        # The card of a result without details shows its content; it shows
        # the preview without the model's instructions instead.
        details = CustomToolCallSummary(
            tool_name=context.calls[0].name,
            response_type="text",
            tool_result=None,
            spilled=spilled,
        )
    return result.model_copy(update={"content": content, "details": details})


def _spill_full_text(
    turn: SandboxTurn, context: ToolResultContext, full: str, *, code_mode: bool
) -> ToolResult:
    """A result whose content is the tool's cut of `full`: `full` goes to
    the file, and the model keeps the content with the file's path. The card
    of a cell observation or an exec call shows the head and the tail of
    `full` with a note."""
    result = context.result
    try:
        saved = _save(turn, context, *_utf8_parts(full))
    except Exception:
        logger.exception("tool_result_spill_failed call=%s", context.calls[0].id)
        return result.model_copy(
            update={"content": f"{result.content}\n\n{SPILL_FAILED_NOTE}"}
        )
    details = result.details
    head, tail = _head_and_tail(full)
    if isinstance(details, CodeModeExecutionResult) and details.closing is None:
        # The output, the result and the error are all in `full`.
        details = details.model_copy(
            update={
                "stdout": "",
                "result": None,
                "error": None,
                "spilled": SpilledOutput(head=head, tail=tail),
            }
        )
    elif isinstance(details, SandboxExecResult):
        details = details.model_copy(
            update={"output": "", "spilled": SpilledOutput(head=head, tail=tail)}
        )
    return result.model_copy(
        update={
            "content": f"{result.content}\n\n"
            + _envelope(saved, FULL_VALUE_NOTE, code_mode=code_mode),
            "details": details,
        }
    )


def _spill_pages(
    turn: SandboxTurn,
    context: ToolResultContext,
    pages: SearchResults,
    *,
    code_mode: bool,
) -> ToolResult:
    """A result whose content holds excerpts of `pages` (open_url): the file
    holds the pages, one JSON object for each line, and the model keeps the
    excerpts with a list of the pages that names each one's citation number,
    so the model can cite a page that it reads from the file."""
    result = context.result
    try:
        # One encoded copy: the call keeps far less than SPILL_MAX_BYTES.
        saved = _save(
            turn, context, [to_json(page) + b"\n" for page in pages.results], False
        )
    except Exception:
        logger.exception("tool_result_spill_failed call=%s", context.calls[0].id)
        return result.model_copy(
            update={"content": f"{result.content}\n\n{SPILL_FAILED_NOTE}"}
        )
    listed = "".join(
        f"{line}. [{page.document}] "
        + json.dumps(
            truncate_search_result_content(page.title, PAGE_LIST_FIELD_MAX_CHARS),
            ensure_ascii=False,
        )
        + (
            " "
            + json.dumps(
                truncate_search_result_content(page.url, PAGE_LIST_FIELD_MAX_CHARS),
                ensure_ascii=False,
            )
            if page.url
            else ""
        )
        + f": {len(page.content):,} characters\n"
        for line, page in enumerate(pages.results, start=1)
    )
    return result.model_copy(
        update={
            "content": f"{result.content}\n\n"
            + _envelope(
                saved,
                "The pages above are excerpts. The file holds each page whole, "
                "one JSON object for each line; cite a page by its number:\n"
                + listed.rstrip("\n"),
                code_mode=code_mode,
            )
        }
    )
