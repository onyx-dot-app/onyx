"""Cells: code mode programs that keep running across the tool calls of a response.

A cell is one running program. Each `execute_code` or `wait_code` call is one
observation: it reports what the cell did in one time window. `CodeCells` owns the
cells of one response: ids, limits, store commit order and the closing records.
`CodeCell` owns one program: its driver thread, tool calls, output window and
observer.
"""

import json
import threading
import time
from collections import deque
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from functools import partial
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from onyx.agents.models import ToolResultAmendment
from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.llm.constants import APPROX_CHARS_PER_TOKEN
from onyx.llm.models import Message, ToolResult, ToolResultMessage
from onyx.server.metrics import code_mode as metrics
from onyx.tools.interface import CITATIONS_PER_TOOL_CALL, Tool
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolUserFileSnapshot,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    ToolCallException,
    ToolContext,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CODE_MODE_CALL_DETAIL_TYPES,
    STOPPED_BEFORE_END,
    CellCallRecord,
    CellClosing,
    CellClosingReason,
    CellEvent,
    CellObserver,
    ClosedStatus,
    CodeModeCall,
    CodeModeCallDetails,
    CodeModeCallFinished,
    CodeModeCallProgress,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStatus,
    CodeModeStdout,
    DiscardedWrites,
    ExternalCall,
    ObservationCut,
    SandboxLimits,
    SandboxResult,
    StoreCommit,
    StoreSnapshot,
    code_mode_results,
)
from onyx.tools.tool_implementations.code_mode.prompt import (
    closing_line,
    format_content,
)
from onyx.tools.tool_implementations.code_mode.sandbox import (
    BUSY_MESSAGE,
    execute_program,
)
from onyx.tools.tool_implementations.code_mode.store import (
    ProgramStore,
    changed_writes,
    commit_limit_error,
    store_snapshot,
)
from onyx.tools.tool_implementations.code_mode.stubs import (
    ToolFunction,
    ToolStubs,
    program_value,
    tool_arguments,
)
from onyx.tools.tool_implementations.search.models import SearchPlanningResult
from onyx.tools.tool_implementations.utils import truncate_output, truncation_marker
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger
from onyx.utils.pydantic_util import as_base
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()

UNFINISHED_CALL_MESSAGE = "The call did not finish before the program ended."
CANCELLED_CALL_MESSAGE = "The tool call was cancelled."
TERMINATED_MESSAGE = "The cell was terminated."
# Text kept for each call in saved and streamed results. The program receives the
# full result; later calls get less once the cell's budget is spent.
MAX_SAVED_CALL_CHARS = 10_000
MIN_SAVED_CALL_CHARS = 500
MAX_SAVED_EXECUTION_CHARS = 200_000
# Open cells per response.
MAX_OPEN_CELLS = 4
# Cells whose program has not ended, in the server process; each holds a driver
# thread. At this limit, sandbox.MAX_TOOL_CALL_THREADS still gives every program
# a share of 3 tool call threads. Programs give up their sandbox worker
# (sandbox.MAX_SANDBOX_PROCESSES) while they wait on tools, so most of these
# cells wait on tools, not on a worker.
MAX_RUNNING_CELLS = 64
# Progress events kept for an observer while none is attached; call starts and
# ends are always kept.
MAX_BUFFERED_PROGRESS_EVENTS = 1_000
# How long the end of the response waits for a stopped cell's program to end,
# counted from the cell's first stop request (Stop or the end of the response).
STOP_GRACE_SECONDS = 5.0
# The tracing span of a cell, from its start to its program's end.
CELL_SPAN_NAME = "code_mode_cell"

# Tokens of output that one observation returns to the model by default.
DEFAULT_MAX_OUTPUT_TOKENS = 10_000
# Printed text streamed while a cell runs: about the default token budget. The
# observation's saved output replaces it.
LIVE_OUTPUT_CHARS = APPROX_CHARS_PER_TOKEN * DEFAULT_MAX_OUTPUT_TOKENS
# Printed text for an attached observer goes out in batches: at this size, after
# STDOUT_FLUSH_SECONDS, before the next call event, and when the observation ends.
STDOUT_FLUSH_CHARS = 4_096
STDOUT_FLUSH_SECONDS = 0.05

StopReason = Literal["cancelled", "terminated"]


class StdoutCollector:
    """Collects printed text within a budget; the first `live_chars` are shown live.

    It keeps the first and the last half of `max_chars` characters and counts the
    ones in between, so a cut text always says how much it omitted.
    """

    def __init__(self, max_chars: int, live_chars: int) -> None:
        self._head_limit = max_chars // 2
        self._tail_limit = max_chars - self._head_limit
        self._live_limit = live_chars
        self._head: list[str] = []
        self._head_chars = 0
        self._tail: deque[str] = deque()
        self._tail_chars = 0
        self._dropped = 0
        self._live_chars = 0
        self._live_stopped = False

    def write(self, text: str) -> str:
        """Collect `text`; returns the part to show live."""
        live = self._live(text)
        head = text[: max(0, self._head_limit - self._head_chars)]
        if head:
            self._head.append(head)
            self._head_chars += len(head)
        rest = text[len(head) :]
        if rest:
            self._tail.append(rest)
            self._tail_chars += len(rest)
            self._trim_tail()
        return live

    def _trim_tail(self) -> None:
        excess = self._tail_chars - self._tail_limit
        while excess > 0:
            first = self._tail[0]
            if len(first) <= excess:
                self._tail.popleft()
                cut = len(first)
            else:
                self._tail[0] = first[excess:]
                cut = excess
            self._tail_chars -= cut
            self._dropped += cut
            excess -= cut

    def _live(self, text: str) -> str:
        if self._live_stopped:
            return ""
        remaining = self._live_limit - self._live_chars
        if len(text) > remaining:
            text = text[:remaining] + "\n... [further output is not shown live]\n"
            self._live_stopped = True
        self._live_chars += len(text)
        return text

    @property
    def dropped(self) -> int:
        """Characters the collector dropped from the middle."""
        return self._dropped

    @property
    def text(self) -> str:
        return self.cut(self._head_limit + self._tail_limit)

    def cut(self, max_chars: int) -> str:
        """The collected text within `max_chars`, cut in the middle; the marker
        counts every character omitted, also those the collector dropped."""
        head = "".join(self._head)
        tail = "".join(self._tail)
        if not self._dropped:
            # Nothing dropped: head and tail are one contiguous text.
            return truncate_output(
                head + tail, max_chars, label="code mode output", keep_tail=True
            )
        kept_head = min(max_chars // 2, len(head))
        kept_tail = min(max_chars - kept_head, len(tail))
        omitted = self._dropped + len(head) - kept_head + len(tail) - kept_tail
        return (
            head[:kept_head]
            + truncation_marker(omitted)
            + (tail[len(tail) - kept_tail :] if kept_tail else "")
        )


class SequentialCalls:
    """Runs the calls to one sequential tool one at a time, as they run outside
    programs. A waiting call ends with AgentCancelled once its cancellation is set."""

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._busy = False

    @contextmanager
    def turn(self, cancellation: CancellationSignal) -> Iterator[None]:
        def wake() -> None:
            with self._changed:
                self._changed.notify_all()

        with cancellation.on_cancel(wake), self._changed:
            self._changed.wait_for(lambda: not self._busy or cancellation.cancelled)
            cancellation.check()
            self._busy = True
        try:
            yield
        finally:
            with self._changed:
                self._busy = False
                self._changed.notify_all()


def durable_details(details: BaseModel | None) -> CodeModeCallDetails | None:
    """The inner details that a saved code mode result can hold, as their saved type.

    Subclasses can carry state that the saved union cannot hold, so they become
    their saved base type.
    """
    for kind in CODE_MODE_CALL_DETAIL_TYPES:
        if isinstance(details, kind):
            durable = as_base(details, kind)
            if (
                isinstance(durable, CustomToolCallSummary)
                and durable.structured_result is not None
            ):
                # Saved results exclude it; cleared so that the cell's call records
                # do not hold it for the rest of the run. A copy, since `as_base`
                # can return the live details.
                durable = durable.model_copy(update={"structured_result": None})
            # `kind` is a member of the CodeModeCallDetails union.
            return cast(CodeModeCallDetails, durable)
    return None


def _bounded(text: str, max_chars: int) -> str:
    return truncate_output(text, max_chars, label="code mode call", keep_tail=True)


def _bounded_details(
    details: CodeModeCallDetails | None, max_chars: int
) -> CodeModeCallDetails | None:
    if isinstance(details, CustomToolCallSummary) and not isinstance(
        details.tool_result, CustomToolUserFileSnapshot
    ):
        value = details.tool_result
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        if len(text) <= max_chars:
            return details
        return details.model_copy(update={"tool_result": _bounded(text, max_chars)})
    if isinstance(details, (LlmPythonExecutionResult, LlmBashExecutionResult)):
        return details.model_copy(
            update={
                "stdout": _bounded(details.stdout, max_chars),
                "stderr": _bounded(details.stderr, max_chars),
            }
        )
    if isinstance(details, FileReadResult):
        return details.model_copy(
            update={
                "preview_start": _bounded(details.preview_start, max_chars),
                "preview_end": _bounded(details.preview_end, max_chars),
            }
        )
    if isinstance(details, ToolExecutionError):
        return details.model_copy(
            update={"message": _bounded(details.message, max_chars)}
        )
    return details


def _bounded_call(call: CodeModeCall, max_chars: int) -> CodeModeCall:
    """The call with its content and large detail text cut to about `max_chars` each."""
    return call.model_copy(
        update={
            "content": _bounded(call.content, max_chars),
            "details": _bounded_details(call.details, max_chars),
        }
    )


def _saved_call_chars(call: CodeModeCall) -> int:
    """Characters a call adds to a saved result; documents are saved separately."""
    details = call.details
    detail_chars = (
        0
        if details is None or isinstance(details, SearchDocsResponse)
        else len(details.model_dump_json())
    )
    return len(call.content) + detail_chars


class CitationAllocator:
    """Citation number blocks for the nested calls of one response.

    Calls in flight at the same time get separate blocks. Once none is in flight,
    the next block starts after the highest number used.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 1
        self._window_start = 1
        self._in_flight = 0
        self._max_used = 0
        self._mapping: dict[int, str] = {}

    def reserve(self, floor: int) -> int:
        with self._lock:
            start = max(self._next, floor)
            if self._in_flight == 0:
                self._window_start = start
            self._next = start + CITATIONS_PER_TOOL_CALL
            self._in_flight += 1
            return start

    def release(self, citation_mapping: dict[int, str]) -> None:
        with self._lock:
            self._mapping.update(citation_mapping)
            self._max_used = max([self._max_used, *citation_mapping])
            self._in_flight -= 1
            if self._in_flight == 0:
                self._next = max(self._max_used + 1, self._window_start)

    def mapping(self) -> dict[int, str]:
        with self._lock:
            return dict(self._mapping)


def _call_result(
    tool: Tool, invocation: ToolInvocation, context: ToolContext
) -> ToolResult:
    outcome = tool.run(invocation, context)
    if not isinstance(outcome, ToolResult):
        # with_code_mode keeps tools that wait for child runs direct.
        raise TypeError(f"{tool.name} returned no result inside a program")
    return outcome


class _RunningCells:
    """The process-wide budget of running cells (MAX_RUNNING_CELLS)."""

    def __init__(self, limit: int) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._running = 0

    def acquire(self) -> bool:
        with self._lock:
            if self._running >= self._limit:
                return False
            self._running += 1
            metrics.CELLS_RUNNING.set(self._running)
            return True

    def release(self) -> None:
        with self._lock:
            self._running -= 1
            metrics.CELLS_RUNNING.set(self._running)


_running_cells = _RunningCells(MAX_RUNNING_CELLS)
metrics.CELLS_LIMIT.set(MAX_RUNNING_CELLS)


def _rejected(text: str) -> ToolCallException:
    return ToolCallException(message=text, llm_facing_message=text)


def _recorded_cell_ids(messages: Sequence[Message]) -> set[int]:
    """Ids of the cells that saved results in `messages`."""
    return {details.cell_id for _, details in code_mode_results(messages)}


def _closing_amendment(
    call_id: str,
    result: ToolResult,
    details: CodeModeExecutionResult,
    closing: CellClosing,
) -> ToolResultAmendment:
    """The saved result of a cell's observation, with the cell's closing record."""
    return ToolResultAmendment(
        call_id=call_id,
        result=ToolResult(
            content=f"{result.content}\n\n{closing_line(details.cell_id, closing)}",
            details=details.model_copy(update={"closing": closing}),
            is_error=result.is_error,
        ),
    )


def _interrupted_amendments(
    results: Sequence[ToolResultMessage], live_cell_ids: Collection[int]
) -> list[ToolResultAmendment]:
    """Closing records for cells of a restored run: their last saved observation
    reports them running, and no live cell continues them."""
    last = {
        details.cell_id: (message, details)
        for message, details in code_mode_results(results)
    }
    return [
        _closing_amendment(
            message.tool_call_id,
            message,
            details,
            CellClosing(reason="interrupted", status="cancelled"),
        )
        for cell_id, (message, details) in last.items()
        if cell_id not in live_cell_ids
        and details.status == "running"
        and details.closing is None
    ]


class StoreLimitError(Exception):
    """A commit that would exceed a store limit."""


class _StoreCommits:
    """Store commits of one response.

    Each commit gets the next ordinal of the branch when its cell ends, so
    the fold over saved records gives the store of the live completion order in
    any message order.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._commits: list[StoreCommit] = []

    def snapshot(self, recorded_results: Sequence[Message]) -> StoreSnapshot:
        with self._lock:
            return store_snapshot(recorded_results, self._commits)

    def commit(
        self, writes: Mapping[str, JsonValue], recorded_results: Sequence[Message]
    ) -> StoreCommit | None:
        """Raises StoreLimitError if the commit would exceed a store limit."""
        with self._lock:
            # Against the store at commit time: another cell may have changed it
            # since this one started.
            current = store_snapshot(recorded_results, self._commits)
            writes = changed_writes(current.values, writes)
            if not writes:
                return None
            error = commit_limit_error(current, writes)
            if error is not None:
                raise StoreLimitError(error)
            commit = StoreCommit(ordinal=current.last_ordinal + 1, writes=writes)
            self._commits.append(commit)
            return commit


class Program(BaseModel):
    """A program to run as a cell, with the tools it can call. It stays here, not
    in models.py: ToolStubs and SequentialCalls import models.py."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    code: str
    stubs: ToolStubs
    limits: SandboxLimits
    # Calls to these tools, by tool name, run one at a time.
    sequential_calls: Mapping[str, SequentialCalls]


class CodeCell:
    """One running program and its observations.

    The driver runs on its own thread. Each event (printed text, call start,
    progress, call end) goes to the attached observer, or waits in the window for
    the next one. The lock orders events with observer changes.
    """

    def __init__(
        self,
        *,
        cell_id: int,
        program: Program,
        citations: CitationAllocator,
        store: _StoreCommits,
        invocation: ToolInvocation,
        context: ToolContext,
    ) -> None:
        self.id = cell_id
        self._program = program
        self._citations = citations
        self._store = store
        # The execute_code call that started the cell; nested call ids use it.
        self._call_id = invocation.call_id
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        # Stops the program and its nested calls: set when the cell is stopped or
        # its program ends.
        self._stopping = CancellationSignal()
        self._started_at = time.monotonic()
        self._calls: dict[int, CellCallRecord] = {}
        self._saved_chars = 0
        # The current window: its number, printed text, and events kept for the
        # next observer while none is attached.
        self._window = 0
        self._stdout = self._collector()
        self._events: list[CellEvent] = []
        self._progress_events = 0
        # Printed text not yet sent to the attached observer.
        self._pending_stdout: list[str] = []
        self._pending_stdout_chars = 0
        # When the oldest pending text was printed; the observer's thread sends it
        # STDOUT_FLUSH_SECONDS later.
        self._pending_since = 0.0
        # The attached observer. After Stop it stays attached; `close` saves it.
        self._observer: CellObserver | None = None
        self._observations = 0
        # Context and messages of the latest observation, for nested calls.
        self._source = invocation
        self._context = context
        self._yielded = False
        self._stop: StopReason | None = None
        # When the first stop was requested; the grace to end counts from it.
        self._stopped_at: float | None = None
        # The program's end, how the cell ended, and the keys of its store()
        # writes that did not commit; set together.
        self._end: SandboxResult | None = None
        self._ended_as: ClosedStatus | None = None
        self._discarded: DiscardedWrites | None = None
        self._commit: StoreCommit | None = None
        # The final result was returned, or the response ended; events are dropped.
        self._closed = False
        # The last saved observation, with its call id, while it reports the cell
        # running.
        self._last: tuple[str, ToolResult, CodeModeExecutionResult] | None = None
        # Observations taken but not yet formatted; `close` waits for them.
        self._formatting = 0

    def _collector(self) -> StdoutCollector:
        return StdoutCollector(
            self._program.limits.max_output_chars, live_chars=LIVE_OUTPUT_CHARS
        )

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def start(
        self, snapshot: StoreSnapshot, *, yield_seconds: float, max_tokens: int
    ) -> ToolResult:
        """Run the program; returns observation 0 to the call that started it."""
        with self._lock:
            if self._observations:
                raise RuntimeError(f"Cell {self.id} already started")
            observer = self._attach(self._source, self._context, max_tokens)
        try:
            start_thread_future(
                partial(self._drive, snapshot, observer.invocation.cancellation),
                name=f"code-mode-cell-{self.id}",
            )
        except BaseException:
            _running_cells.release()
            raise
        return self._observe(observer, yield_seconds)

    def observe(
        self,
        invocation: ToolInvocation,
        context: ToolContext,
        *,
        yield_seconds: float,
        max_tokens: int,
        terminate: bool,
    ) -> ToolResult:
        """A wait_code observation: new output, the final result, or termination."""
        with self._lock:
            if self._closed:
                raise _rejected(f"Cell {self.id} already returned its final result.")
            if self._observer is not None:
                raise _rejected(f"Cell {self.id} already has an active wait_code call.")
            observer = self._attach(invocation, context, max_tokens)
        if terminate:
            self.stop("terminated")
        return self._observe(observer, yield_seconds)

    def stop(self, reason: StopReason) -> None:
        """Stop the program; the first reason wins. No-op once it ended."""
        with self._lock:
            if self._stop is not None or self._end is not None:
                return
            self._stop = reason
            self._stopped_at = time.monotonic()
            self._changed.notify_all()
        self._stopping.cancel()

    def wait_ended(self) -> None:
        """Wait for the program to end, at most STOP_GRACE_SECONDS after the first
        stop request."""
        with self._lock:
            stopped_at = (
                time.monotonic() if self._stopped_at is None else self._stopped_at
            )
            self._changed.wait_for(
                lambda: self._end is not None,
                max(0.0, stopped_at + STOP_GRACE_SECONDS - time.monotonic()),
            )

    def running_calls(self) -> list[str]:
        """Nested calls whose thread has not returned, as `[index] name`."""
        with self._lock:
            return [
                f"[{index}] {record.call.function_name}"
                for index, record in sorted(self._calls.items())
                if record.thread_alive
            ]

    def close(self, reason: CellClosingReason) -> ToolResultAmendment | None:
        """The final record of the cell when the response ends or the run pauses.

        An observation that Stop interrupted gets its result: the cell's end, or
        how it stopped. Otherwise the last saved observation, when it reports the
        cell running, gets the closing record. None for a cell that already
        reported its end.
        """
        with self._lock:
            if self._closed:
                return None
            observer = self._observer
            taken = (
                self._take(observer, final=True)
                if observer is not None
                else self._closing(reason)
            )
        if isinstance(taken, ObservationCut):
            return ToolResultAmendment(
                call_id=taken.call_id, result=self._formatted(taken)
            )
        return taken

    def _closing(self, reason: CellClosingReason) -> ToolResultAmendment | None:
        """Close the cell: the closing record for its last saved observation, when
        that reports it running. The caller holds the lock."""
        # An observation being formatted may still report the cell running.
        self._changed.wait_for(lambda: self._formatting == 0)
        self._closed = True
        if self._last is None:
            return None
        call_id, result, details = self._last
        return _closing_amendment(
            call_id,
            result,
            details,
            CellClosing(
                reason=reason,
                status=self._final_status(),
                # The model reads only the closing line, not this output.
                stdout=self._stdout.cut(LIVE_OUTPUT_CHARS),
                calls=self._window_calls(final=True),
                commit=self._commit,
                tool_call_count=len(self._calls),
            ),
        )

    # Observations

    def _attach(
        self, invocation: ToolInvocation, context: ToolContext, max_tokens: int
    ) -> CellObserver:
        """Make `invocation` the observer and send it the window so far; the
        caller holds the lock."""
        observer = CellObserver(
            invocation=invocation, number=self._observations, max_tokens=max_tokens
        )
        self._observations += 1
        self._observer = observer
        self._source = invocation
        self._context = context
        self._yielded = False
        # Calls that were running when the previous observation ended.
        for _, record in sorted(self._calls.items()):
            if record.started_in < self._window and record.in_window(self._window):
                self._publish(CodeModeCallStarted(call=record.call))
        for event in self._events:
            self._publish(event)
        self._events.clear()
        return observer

    def _observe(self, observer: CellObserver, yield_seconds: float) -> ToolResult:
        deadline = time.monotonic() + yield_seconds
        cancellation = observer.invocation.cancellation

        def wake() -> None:
            with self._lock:
                self._changed.notify_all()

        with cancellation.on_cancel(wake), self._lock:
            while not (
                self._end is not None or self._yielded or cancellation.cancelled
            ):
                now = time.monotonic()
                if now >= deadline:
                    break
                if self._pending_stdout:
                    flush_at = self._pending_since + STDOUT_FLUSH_SECONDS
                    if now >= flush_at:
                        self._flush_stdout()
                        continue
                    self._changed.wait(min(deadline, flush_at) - now)
                else:
                    self._changed.wait(deadline - now)
            if cancellation.cancelled:
                # The run's cancellation also stops the cell. The observer stays
                # attached, so `close` saves this observation at the run's end.
                raise AgentCancelled()
            cut = self._take(observer, final=False)
        return self._formatted(cut)

    def _final_status(self) -> ClosedStatus:
        """How the cell ended, or how it is stopping; the caller holds the lock."""
        if self._ended_as is not None:
            return self._ended_as
        return "cancelled" if self._stop == "cancelled" else "terminated"

    def _window_calls(self, *, final: bool) -> list[CodeModeCall]:
        """Calls that ended in the window, and calls still running, which are
        unfinished when nothing reports them later; the caller holds the lock."""
        return [
            record.call
            if record.ended_in is not None
            else record.call.model_copy(
                update={
                    "state": "unfinished" if final else "running",
                    "content": UNFINISHED_CALL_MESSAGE if final else "",
                }
            )
            for _, record in sorted(self._calls.items())
            if record.in_window(self._window)
        ]

    def _take(self, observer: CellObserver, *, final: bool) -> ObservationCut:
        """End the observation and start a new window. `final` reports the cell's
        end even when its program has not ended. The caller holds the lock and
        passes the cut to `_formatted`."""
        self._flush_stdout()
        end = self._end
        status: CodeModeStatus = (
            self._final_status() if final else (self._ended_as or "running")
        )
        budget = observer.max_tokens
        saved_chars = APPROX_CHARS_PER_TOKEN * budget
        details = CodeModeExecutionResult(
            cell_id=self.id,
            observation=observer.number,
            code=self._program.code if observer.number == 0 else "",
            status=status,
            stdout=self._stdout.text,
            result=None if end is None else end.result,
            error=TERMINATED_MESSAGE
            if status == "terminated"
            else (None if end is None else end.error),
            duration_seconds=time.monotonic() - self._started_at
            if end is None
            else end.duration_seconds,
            calls=self._window_calls(final=final),
            commit=self._commit,
            tool_call_count=len(self._calls),
        )
        # The saved observation keeps each part within about the budget.
        saved = details.model_copy(
            update={
                "stdout": self._stdout.cut(saved_chars),
                "result": None
                if details.result is None
                else _bounded(details.result, saved_chars),
                "error": None
                if details.error is None
                else _bounded(details.error, saved_chars),
            }
        )
        cut = ObservationCut(
            call_id=observer.invocation.call_id,
            details=details,
            saved=saved,
            max_tokens=budget,
            end=end,
            discarded=self._discarded,
            elided_chars=self._stdout.dropped,
        )
        self._window += 1
        self._stdout = self._collector()
        self._progress_events = 0
        self._observer = None
        if end is not None or final:
            self._closed = True
        self._formatting += 1
        return cut

    def _formatted(self, cut: ObservationCut) -> ToolResult:
        """The result of a taken observation; formats outside the lock."""
        status = cut.details.status
        formatted: ToolResult | None = None
        try:
            formatted = ToolResult(
                content=format_content(
                    cut.details,
                    max_tokens=cut.max_tokens,
                    end=cut.end,
                    discarded=cut.discarded,
                    elided_chars=cut.elided_chars,
                ),
                details=cut.saved,
                is_error=status in ("failed", "timed_out", "cancelled"),
            )
            return formatted
        finally:
            with self._lock:
                if formatted is not None and status == "running":
                    self._last = (cut.call_id, formatted, cut.saved)
                self._formatting -= 1
                self._changed.notify_all()

    # Events; `_publish` and `_emit` need the lock.

    def _publish(self, details: CellEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer.invocation.update(ToolProgress(details=details))
        except AgentCancelled:
            pass

    def _emit(self, details: CellEvent) -> None:
        if self._closed:
            return
        if self._observer is not None:
            if isinstance(details, CodeModeStdout):
                self._buffer_stdout(details.text)
            else:
                self._flush_stdout()
                self._publish(details)
            return
        events = self._events
        if isinstance(details, CodeModeStdout) and events:
            previous = events[-1]
            if isinstance(previous, CodeModeStdout):
                events[-1] = CodeModeStdout(text=previous.text + details.text)
                return
        if isinstance(details, CodeModeCallProgress):
            if self._progress_events >= MAX_BUFFERED_PROGRESS_EVENTS:
                return
            self._progress_events += 1
        events.append(details)

    def _buffer_stdout(self, text: str) -> None:
        self._pending_stdout.append(text)
        self._pending_stdout_chars += len(text)
        if self._pending_stdout_chars >= STDOUT_FLUSH_CHARS:
            self._flush_stdout()
        elif len(self._pending_stdout) == 1:
            self._pending_since = time.monotonic()
            # The waiting observer starts its flush interval.
            self._changed.notify_all()

    def _flush_stdout(self) -> None:
        """Send the buffered printed text to the attached observer."""
        if not self._pending_stdout:
            return
        text = "".join(self._pending_stdout)
        self._pending_stdout.clear()
        self._pending_stdout_chars = 0
        self._publish(CodeModeStdout(text=text))

    def _send(self, details: CellEvent) -> None:
        with self._lock:
            self._emit(details)

    # Driver

    def _drive(
        self, snapshot: StoreSnapshot, run_cancellation: CancellationSignal
    ) -> None:
        # The cell's span is the parent of its nested tool spans.
        try:
            with function_span(CELL_SPAN_NAME, input=self._program.code) as span:
                store = ProgramStore(snapshot)
                end = self._execute(store, run_cancellation)
                self._end_program(end, store)
                with self._lock:
                    status = self._final_status()
                    metrics.observe_program_end(status, end.duration_seconds)
                    span.span_data.output = status
                    span.span_data.metadata = {
                        "code_mode.cell_id": self.id,
                        "code_mode.status": status,
                        "code_mode.duration_seconds": end.duration_seconds,
                        "code_mode.tool_call_count": len(self._calls),
                        "code_mode.tool_names": sorted(
                            {record.call.tool_name for record in self._calls.values()}
                        ),
                    }
        finally:
            _running_cells.release()

    def _execute(
        self, store: ProgramStore, run_cancellation: CancellationSignal
    ) -> SandboxResult:
        program = self._program
        try:
            with run_cancellation.on_cancel(lambda: self.stop("cancelled")):
                return execute_program(
                    program.code,
                    stubs=program.stubs.text,
                    function_names=frozenset(program.stubs.functions),
                    plain_functions=store.functions,
                    async_functions=program.stubs.async_functions,
                    handler=self._call,
                    cancellation=self._stopping,
                    limits=program.limits,
                    on_print=self._print,
                    on_yield=self._yield_control,
                )
        except BaseException as error:
            logger.exception("Code mode cell %s stopped with an error", self.id)
            return SandboxResult(
                status="failed", error=f"{type(error).__name__}: {error}"
            )

    def _end_program(self, end: SandboxResult, store: ProgramStore) -> None:
        """Commit the program's store writes, and make its end visible."""
        # Calls the program never awaited stop with it.
        self._stopping.cancel()
        with self._lock:
            source = self._source
        # Before the end is visible, so the observation that reports it has the
        # commit.
        commit: StoreCommit | None = None
        discard_reason: str | None = None if end.commits_store else STOPPED_BEFORE_END
        if end.commits_store:
            try:
                commit = self._store.commit(store.writes, source.recorded_results)
            except StoreLimitError as error:
                discard_reason = str(error)
        with self._lock:
            self._commit = commit
            self._discarded = (
                None
                if discard_reason is None
                else DiscardedWrites(
                    keys=tuple(store.changed_writes), reason=discard_reason
                )
            )
            for record in self._calls.values():
                if record.ended_in is None:
                    self._record(
                        record.call.model_copy(
                            update={
                                "content": UNFINISHED_CALL_MESSAGE,
                                "state": "unfinished",
                            }
                        )
                    )
            self._ended_as = (
                "terminated"
                if end.status == "cancelled" and self._stop == "terminated"
                else end.status
            )
            self._end = end
            self._changed.notify_all()

    def _print(self, text: str) -> None:
        with self._lock:
            live = self._stdout.write(text)
            if live:
                self._emit(CodeModeStdout(text=live))

    def _yield_control(self) -> None:
        with self._lock:
            if self._observer is not None:
                self._yielded = True
                self._changed.notify_all()

    def _call(self, external: ExternalCall) -> object:
        function = self._program.stubs.functions[external.function_name]
        started = CodeModeCall(
            index=external.index,
            id=f"{self._call_id}:{external.index}",
            tool_name=function.tool.name,
            tool_id=function.tool.id,
            function_name=function.function_name,
            arguments=tool_arguments(function, external.kwargs),
            state="running",
        )
        with self._lock:
            self._calls[external.index] = CellCallRecord(
                call=started, started_in=self._window
            )
            context = self._context
            source = self._source
            self._emit(CodeModeCallStarted(call=started))
        try:
            return self._run_call(function, started, context, source)
        finally:
            with self._lock:
                self._calls[external.index].thread_alive = False

    def _run_call(
        self,
        function: ToolFunction,
        started: CodeModeCall,
        context: ToolContext,
        source: ToolInvocation,
    ) -> object:
        inner_tool = function.tool
        cites = function.result.cites
        start = (
            self._citations.reserve(context.next_citation_num)
            if cites
            else context.next_citation_num
        )
        used: dict[int, str] = {}
        try:
            inner_context = context.model_copy(
                update={
                    "next_citation_num": start,
                    "citation_mapping": {
                        **context.citation_mapping,
                        **self._citations.mapping(),
                    },
                }
            )
            inner_invocation = ToolInvocation(
                call_id=started.id,
                call_index=0,
                arguments=started.arguments,
                cancellation=self._stopping,
                update=lambda progress: self._send(
                    CodeModeCallProgress(
                        index=started.index,
                        content=progress.content,
                        details=progress.details,
                    )
                ),
                messages=source.messages,
                recorded_results=source.recorded_results,
                agents=None,
                trace_metadata={
                    "code_mode.call_id": self._call_id,
                    "code_mode.cell_id": self.id,
                    "code_mode.index": started.index,
                    "code_mode.function_name": started.function_name,
                },
            )
            sequential = self._program.sequential_calls.get(inner_tool.name)
            # Nested model and HTTP work stops when the cell stops or ends.
            try:
                with (
                    sequential.turn(self._stopping)
                    if sequential is not None
                    else nullcontext(),
                    cancellation_scope(self._stopping),
                ):
                    result = _call_result(inner_tool, inner_invocation, inner_context)
            except AgentCancelled as error:
                # The program sees an error; the cell's end records the call as
                # unfinished.
                raise RuntimeError(CANCELLED_CALL_MESSAGE) from error
            details = durable_details(result.details)
            if isinstance(details, SearchDocsResponse):
                used = dict(details.citation_mapping)
        finally:
            if cites:
                self._citations.release(used)
        # Bounded before the lock; `_record` cuts it further once the cell's
        # budget is spent.
        ended = _bounded_call(
            started.model_copy(
                update={
                    "content": result.content,
                    "state": "error" if result.is_error else "ok",
                    "details": details,
                    "metadata": result.metadata
                    if isinstance(result.metadata, SearchPlanningResult)
                    else None,
                }
            ),
            MAX_SAVED_CALL_CHARS,
        )
        with self._lock:
            if self._calls[started.index].ended_in is None:
                self._record(ended)
        return program_value(function, result)

    def _record(self, call: CodeModeCall) -> None:
        """Bound, keep and send an ended call; the caller holds the lock."""
        remaining = MAX_SAVED_EXECUTION_CHARS - self._saved_chars
        limit = min(MAX_SAVED_CALL_CHARS, max(MIN_SAVED_CALL_CHARS, remaining))
        if limit < MAX_SAVED_CALL_CHARS:
            call = _bounded_call(call, limit)
        self._saved_chars += _saved_call_chars(call)
        record = self._calls[call.index]
        record.call = call
        record.ended_in = self._window
        self._emit(CodeModeCallFinished(call=call))


class CodeCells:
    """The cells of one response.

    Ids are unique in a conversation branch: 1 + the highest id in the recorded
    messages and in this response. When the response ends, `finish` stops every
    open cell and returns the final records.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cells: dict[int, CodeCell] = {}
        self._highest_id = 0
        self._finished = False
        self._citations = CitationAllocator()
        self._store = _StoreCommits()

    def start(
        self,
        program: Program,
        invocation: ToolInvocation,
        context: ToolContext,
        *,
        yield_seconds: float,
        max_tokens: int,
    ) -> ToolResult:
        """Start `program` as a new cell and return its first observation."""
        with self._lock:
            if self._finished:
                raise _rejected("The response has ended; no new cell can start.")
            open_ids = sorted(
                cell_id for cell_id, cell in self._cells.items() if not cell.closed
            )
            if len(open_ids) >= MAX_OPEN_CELLS:
                names = ", ".join(str(cell_id) for cell_id in open_ids)
                raise _rejected(
                    f"At most {MAX_OPEN_CELLS} cells can be open in one response. "
                    f"Open cells: {names}. Get their results with wait_code, or stop "
                    "one with wait_code(cell_id=N, terminate=true)."
                )
            if not _running_cells.acquire():
                metrics.CELL_BUSY_REJECTIONS.inc()
                raise _rejected(BUSY_MESSAGE)
            try:
                history = _recorded_cell_ids(invocation.recorded_results)
                cell_id = max(self._highest_id, *history, 0) + 1
                self._highest_id = cell_id
                snapshot = self._store.snapshot(invocation.recorded_results)
                cell = CodeCell(
                    cell_id=cell_id,
                    program=program,
                    citations=self._citations,
                    store=self._store,
                    invocation=invocation,
                    context=context,
                )
                self._cells[cell_id] = cell
            except BaseException:
                _running_cells.release()
                raise
        # The cell's driver releases the running cell.
        return cell.start(snapshot, yield_seconds=yield_seconds, max_tokens=max_tokens)

    def wait(
        self,
        cell_id: int,
        invocation: ToolInvocation,
        context: ToolContext,
        *,
        yield_seconds: float,
        max_tokens: int,
        terminate: bool,
    ) -> ToolResult:
        with self._lock:
            cell = self._cells.get(cell_id)
        if cell is None:
            if cell_id in _recorded_cell_ids(invocation.recorded_results):
                raise _rejected(
                    f"Cell {cell_id} stopped when its response ended or its run "
                    "paused. Start a new execute_code call."
                )
            raise _rejected(f"Cell {cell_id} does not exist.")
        return cell.observe(
            invocation,
            context,
            yield_seconds=yield_seconds,
            max_tokens=max_tokens,
            terminate=terminate,
        )

    def finish(self, results: Sequence[ToolResultMessage]) -> list[ToolResultAmendment]:
        """Stop every open cell and return the final records of the response's
        cells: the result of each observation that Stop interrupted, and the
        closing record of each cell whose last saved observation reports it
        running. A cell stopped by Stop reports `cancelled`.

        `results` are the recorded tool results of the run, which hold the running
        observations of a restored run. Each cell gets STOP_GRACE_SECONDS from its
        first stop request (Stop or this call) to end.
        """
        with self._lock:
            self._finished = True
        return self._close_all(results, "response_ended")

    def suspend(
        self, results: Sequence[ToolResultMessage]
    ) -> list[ToolResultAmendment]:
        """Stop every open cell when the run pauses, and return final records as
        `finish` does. Later calls can start new cells."""
        return self._close_all(results, "suspended")

    def _close_all(
        self, results: Sequence[ToolResultMessage], reason: CellClosingReason
    ) -> list[ToolResultAmendment]:
        with self._lock:
            cells = list(self._cells.values())
        for cell in cells:
            cell.stop("terminated")
        for cell in cells:
            cell.wait_ended()
        amendments = [
            amendment for cell in cells if (amendment := cell.close(reason)) is not None
        ]
        for cell in cells:
            running = cell.running_calls()
            if running:
                logger.warning(
                    "Code mode cell %s: calls still running after it closed (%s): %s",
                    cell.id,
                    reason,
                    ", ".join(running),
                )
        return [
            *amendments,
            *_interrupted_amendments(results, {cell.id for cell in cells}),
        ]
