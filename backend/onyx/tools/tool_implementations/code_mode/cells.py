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
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from functools import partial
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from onyx.agents.models import ReleaseFailed, ToolResultAmendment
from onyx.agents.tools import (
    BeforeToolCallFailed,
    PendingToolInput,
    ToolInvocation,
    ToolProgress,
)
from onyx.chat.files import build_python_chat_files_from_search_docs
from onyx.chat.models import StagedChatFiles
from onyx.chat.tool_results import merged_chat_files, staged_result_details
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.llm.constants import APPROX_CHARS_PER_TOKEN
from onyx.llm.models import Message, ToolCall, ToolResult, ToolResultMessage
from onyx.server.metrics import code_mode as metrics
from onyx.tools.constants import PYTHON_TOOL_NAME
from onyx.tools.interface import CITATIONS_PER_TOOL_CALL, Tool
from onyx.tools.models import (
    ChatFile,
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
    LostStoreWrites,
    ObservationCut,
    SandboxLimits,
    SandboxResult,
    StoreCommit,
    StoreSnapshot,
    code_mode_results,
    json_text,
)
from onyx.tools.tool_implementations.code_mode.prompt import (
    closing_heading,
    format_content,
    observation_heading,
)
from onyx.tools.tool_implementations.code_mode.sandbox import (
    BUSY_MESSAGE,
    MAX_RUNNING_CELLS,
    StdoutCollector,
    execute_program,
)
from onyx.tools.tool_implementations.code_mode.store import (
    ProgramStore,
    changed_writes,
    commit_limit_error,
    lost_store_writes,
    store_snapshot,
)
from onyx.tools.tool_implementations.code_mode.stubs import (
    ToolFunction,
    ToolStubs,
    program_value,
    tool_arguments,
)
from onyx.tools.tool_implementations.search.models import SearchPlanningResult
from onyx.tools.tool_implementations.utils import truncate_output
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger
from onyx.utils.pydantic_util import as_base
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()

CANCELLED_CALL_MESSAGE = "The tool call was cancelled."
TERMINATED_MESSAGE = "The cell was terminated."
# Text kept for each call in saved and streamed results. The program receives the
# full result; later calls get less once the cell's budget is spent.
MAX_SAVED_CALL_CHARS = 10_000
MIN_SAVED_CALL_CHARS = 500
MAX_SAVED_EXECUTION_CHARS = 200_000
# Open cells per response.
MAX_OPEN_CELLS = 4
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


def _bounded_arguments(
    arguments: dict[str, JsonValue], max_chars: int, text: str | None = None
) -> dict[str, JsonValue]:
    """`arguments`, whose `json_text` may be given, within about `max_chars` of
    JSON: a value over an equal share becomes its text, cut in the middle."""
    if len(json_text(arguments) if text is None else text) <= max_chars:
        return arguments
    share = max(1, max_chars // len(arguments))
    bounded: dict[str, JsonValue] = {}
    for key, value in arguments.items():
        text = value if isinstance(value, str) else json_text(value)
        bounded[key] = value if len(text) <= share else _bounded(text, share)
    return bounded


def _bounded_call(call: CodeModeCall, max_chars: int) -> CodeModeCall:
    """The call with its arguments, content and large detail text cut to about
    `max_chars` each."""
    return call.model_copy(
        update={
            "arguments": _bounded_arguments(call.arguments, max_chars),
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
    return len(json_text(call.arguments)) + len(call.content) + detail_chars


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
        # Tools that wait for child runs are DIRECT, never program functions.
        raise TypeError(f"{tool.name} returned no result inside a program")
    return outcome


def _decided_result(
    source: ToolInvocation,
    call_id: str,
    tool_name: str,
    arguments: dict[str, JsonValue],
) -> ToolResult | None:
    """The result that the run's before_tool_call hook gives a program's call,
    as it gives a direct call one; None to run the tool.

    A program cannot wait for an answer, so a call that the hook holds for
    input fails with the hook's prompt, as a tool error does.
    """
    if source.before_call is None:
        return None
    decision = source.before_call(
        ToolCall(id=call_id, name=tool_name, arguments=arguments)
    )
    if isinstance(decision, PendingToolInput):
        raise RuntimeError(
            f"{tool_name} needs approval and cannot run inside a program: "
            f"{decision.prompt}"
        )
    return decision


class _RunningCells:
    """The process-wide budget of running cells (MAX_RUNNING_CELLS)."""

    def __init__(self, limit: int) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._running = 0

    def acquire(self, tenant_id: str) -> bool:
        with self._lock:
            if self._running >= self._limit:
                metrics.CELL_BUSY_REJECTIONS.labels(tenant_id=tenant_id).inc()
                return False
            self._running += 1
            metrics.CELLS_RUNNING.set(self._running)
            return True

    def release(self, tenant_id: str, held_seconds: float) -> None:
        """Free a slot that a cell of `tenant_id` held for `held_seconds`."""
        with self._lock:
            self._running -= 1
            metrics.CELLS_RUNNING.set(self._running)
        metrics.CELL_SECONDS.labels(tenant_id=tenant_id).inc(held_seconds)


_running_cells = _RunningCells(MAX_RUNNING_CELLS)


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
    *,
    cell_calls: Sequence[CodeModeCall] = (),
    end: SandboxResult | None = None,
    discarded: DiscardedWrites | None = None,
    elided_chars: int = 0,
) -> ToolResultAmendment:
    """The saved result of a cell's observation, with the cell's closing record.

    The closing record reads like an observation of what the cell did after
    this one; `cell_calls`, `end`, `discarded` and `elided_chars` are as for
    `format_content`.
    """
    closing_text = format_content(
        closing,
        heading=closing_heading(details.cell_id, closing),
        status=closing.status,
        cell_id=details.cell_id,
        cell_calls=cell_calls,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        end=end,
        discarded=discarded,
        elided_chars=elided_chars,
    )
    return ToolResultAmendment(
        call_id=call_id,
        result=ToolResult(
            content=f"{result.content}\n\n{closing_text}",
            details=details.model_copy(update={"closing": closing}),
            is_error=result.is_error,
        ),
    )


def _interrupted_amendments(
    results: Sequence[ToolResultMessage], live_cell_ids: Collection[int]
) -> list[ToolResultAmendment]:
    """Closing records for cells of a restored run: their last saved observation
    reports them running, and no live cell continues them.

    Each record lists the calls that the cell's saved observations hold; a call
    saved as running is unfinished.
    """
    last: dict[int, tuple[ToolResultMessage, CodeModeExecutionResult]] = {}
    calls: dict[int, dict[int, CodeModeCall]] = {}
    for message, details in code_mode_results(results):
        last[details.cell_id] = (message, details)
        calls.setdefault(details.cell_id, {}).update(
            (call.index, call) for call in details.calls
        )
    return [
        _closing_amendment(
            message.tool_call_id,
            message,
            details,
            CellClosing(reason="interrupted", status="cancelled"),
            cell_calls=[
                call if call.state != "running" else call.unfinished()
                for _, call in sorted(calls[cell_id].items())
            ],
        )
        for cell_id, (message, details) in last.items()
        if cell_id not in live_cell_ids
        and details.status == "running"
        and details.closing is None
    ]


class StoreLimitError(Exception):
    """A commit that would exceed a store limit, with the keys of the writes that
    would change the store at commit time."""

    def __init__(self, reason: str, keys: Sequence[str]) -> None:
        super().__init__(reason)
        self.keys = tuple(keys)


class _StoreCommits:
    """Store commits of one response.

    Each commit gets the next ordinal of the branch when its cell ends, so
    the fold over saved records gives the store of the live completion order in
    any message order. A commit stays here until a saved result reports it; it
    names the commit it follows, so a server stop before then also drops the
    saved commits that depend on it (`store_snapshot`). No cell waits for
    another cell's commit to be saved.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._commits: list[StoreCommit] = []
        # The highest ordinal of the dropped commits that a started cell of
        # this response reports; the report covers the dropped commits below it.
        self._reported_through = 0

    def snapshot(self, recorded_results: Sequence[Message]) -> StoreSnapshot:
        """The store for a new cell. The commits it lists as dropped stay listed
        until `reported` marks them."""
        with self._lock:
            return store_snapshot(
                recorded_results,
                self._commits,
                reported_through=self._reported_through,
            )

    def reported(self, snapshot: StoreSnapshot) -> None:
        """A cell started with `snapshot` and reports its dropped commits, so
        later cells do not."""
        with self._lock:
            self._reported_through = max(
                [self._reported_through, *(c.ordinal for c in snapshot.dropped)]
            )

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
                raise StoreLimitError(error, list(writes))
            commit = StoreCommit(
                ordinal=current.last_ordinal + 1,
                follows=current.last_applied,
                writes=writes,
            )
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
        self._tenant_id = metrics.current_tenant_id()
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
        # Files of documents that nested calls found, for later Python calls of
        # the program, as the chat stages them for direct calls.
        self._stages_files = any(
            function.tool.name == PYTHON_TOOL_NAME
            for function in program.stubs.functions.values()
        )
        self._staged_files: list[ChatFile] = []
        # Commits the store dropped before the cell started; observation 0
        # reports them.
        self._lost_store_writes: LostStoreWrites | None = None
        # The observation that yield_control() ended, for its observer to format.
        self._yielded: ObservationCut | None = None
        self._stop: StopReason | None = None
        # When the first stop was requested; the grace to end counts from it.
        self._stopped_at: float | None = None
        # The program's end, how the cell ended, and the keys of its store()
        # writes that did not commit; set together.
        self._end: SandboxResult | None = None
        self._ended_as: ClosedStatus | None = None
        self._discarded: DiscardedWrites | None = None
        self._commit: StoreCommit | None = None
        # The before_tool_call hook raised for a call of the program, until it
        # fails the run: the observation that reports the program's end raises
        # it, or else the cell's closing does.
        self._hook_failure: BeforeToolCallFailed | None = None
        # The final result was returned, or the response ended; events are dropped.
        self._closed = False
        # The last saved observation, with its call id, while it reports the cell
        # running.
        self._last: tuple[str, ToolResult, CodeModeExecutionResult] | None = None
        # Observations taken but not yet formatted; `close` waits for them.
        self._formatting = 0
        # Last, so a cell that exists holds a running-cell slot; `_end_program`
        # releases it.
        if not _running_cells.acquire(self._tenant_id):
            raise _rejected(BUSY_MESSAGE)

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
            self._lost_store_writes = lost_store_writes(snapshot.dropped)
            observer = self._attach(self._source, self._context, max_tokens)
        try:
            start_thread_future(
                partial(self._drive, snapshot, observer.invocation.cancellation),
                name=f"code-mode-cell-{self.id}",
            )
        except Exception as error:
            logger.exception("Code mode cell %s could not start", self.id)
            self._end_program(
                SandboxResult(
                    status="failed",
                    error=f"The cell could not start: {type(error).__name__}: {error}",
                ),
                ProgramStore(snapshot),
            )
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

    def take_hook_failure(self) -> BeforeToolCallFailed | None:
        """The hook failure that no observation raised; it is then raised."""
        with self._lock:
            failure, self._hook_failure = self._hook_failure, None
            return failure

    def _closing(self, reason: CellClosingReason) -> ToolResultAmendment | None:
        """Close the cell: the closing record for its last saved observation, when
        that reports it running. The caller holds the lock."""
        # An observation being formatted may still report the cell running.
        self._changed.wait_for(lambda: self._formatting == 0)
        self._closed = True
        if self._last is None:
            return None
        call_id, result, details = self._last
        status = self._final_status()
        end = self._end
        # A terminated cell's heading says that it stopped; its end adds nothing.
        ended = end if end is not None and status != "terminated" else None
        return _closing_amendment(
            call_id,
            result,
            details,
            CellClosing(
                reason=reason,
                status=status,
                stdout=self._stdout.cut(LIVE_OUTPUT_CHARS),
                calls=self._window_calls(final=True),
                commit=self._commit,
                tool_call_count=len(self._calls),
                result=None
                if ended is None or ended.result is None
                else _bounded(ended.result, LIVE_OUTPUT_CHARS),
                error=None
                if ended is None or ended.error is None
                else _bounded(ended.error, LIVE_OUTPUT_CHARS),
            ),
            cell_calls=self._cell_calls(final=True),
            end=end,
            discarded=self._discarded,
            elided_chars=self._stdout.dropped,
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
        self._yielded = None
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
                self._end is not None
                or self._yielded is not None
                or cancellation.cancelled
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
            cut, self._yielded = self._yielded, None
            if cut is None:
                if cancellation.cancelled:
                    # The run's cancellation also stops the cell. The observer
                    # stays attached, so `close` saves this observation at the
                    # run's end.
                    raise AgentCancelled()
                cut = self._take(observer, final=False)
            failure = None
            if cut.end is not None:
                failure, self._hook_failure = self._hook_failure, None
        result = self._formatted(cut)
        if failure is not None:
            # The run fails, as when the hook raises for a direct call.
            raise failure
        return result

    def _final_status(self) -> ClosedStatus:
        """How the cell ended, or how it is stopping; the caller holds the lock."""
        if self._ended_as is not None:
            return self._ended_as
        return "cancelled" if self._stop == "cancelled" else "terminated"

    def _window_calls(self, *, final: bool) -> list[CodeModeCall]:
        """Calls that ended in the window, and calls still running; the caller
        holds the lock."""
        return [
            call
            for call in self._cell_calls(final=final)
            if self._calls[call.index].in_window(self._window)
        ]

    def _cell_calls(self, *, final: bool) -> list[CodeModeCall]:
        """Every call of the cell in index order. A call still running is
        unfinished when nothing reports it later; the caller holds the lock."""
        return [
            record.call.unfinished()
            if record.ended_in is None and final
            else record.call
            for _, record in sorted(self._calls.items())
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
            lost_store_writes=self._lost_store_writes if observer.number == 0 else None,
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
            cell_calls=self._cell_calls(final=final),
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
                    heading=observation_heading(cut.details),
                    status=status,
                    cell_id=cut.details.cell_id,
                    cell_calls=cut.cell_calls,
                    max_tokens=cut.max_tokens,
                    end=cut.end,
                    discarded=cut.discarded,
                    elided_chars=cut.elided_chars,
                    lost_store_writes=cut.details.lost_store_writes,
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
        with function_span(CELL_SPAN_NAME, input=self._program.code) as span:
            store = ProgramStore(snapshot)
            end = self._execute(store, run_cancellation)
            self._end_program(end, store)
            with self._lock:
                status = self._final_status()
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

    def _execute(
        self, store: ProgramStore, run_cancellation: CancellationSignal
    ) -> SandboxResult:
        program = self._program
        try:
            with run_cancellation.on_cancel(lambda: self.stop("cancelled")):
                return execute_program(
                    program.code,
                    stubs=program.stubs.program_text(program.code),
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
        """Commit the program's store writes, make its end visible, and release
        the cell's running-cell slot."""
        try:
            # Calls the program never awaited stop with it.
            self._stopping.cancel()
            with self._lock:
                # Under the lock with the end, so the observation that reports the
                # end has the commit. A cell whose closing record was already
                # saved reported that it stopped, so it commits nothing: no saved
                # record would hold the commit, and later commits that follow it
                # would be dropped.
                commit: StoreCommit | None = None
                commits = end.commits_store and not self._closed
                discarded = (
                    None
                    if commits
                    else DiscardedWrites(
                        keys=tuple(store.changed_writes), reason=STOPPED_BEFORE_END
                    )
                )
                if commits:
                    try:
                        commit = self._store.commit(
                            store.writes, self._source.recorded_results
                        )
                    except StoreLimitError as error:
                        # Against the store at commit time, which other cells
                        # changed.
                        discarded = DiscardedWrites(keys=error.keys, reason=str(error))
                self._commit = commit
                self._discarded = discarded
                for record in self._calls.values():
                    if record.ended_in is None:
                        self._record(record.call.unfinished())
                self._ended_as = (
                    "terminated"
                    if end.status == "cancelled" and self._stop == "terminated"
                    else end.status
                )
                self._end = end
                metrics.observe_program_end(
                    self._tenant_id, self._ended_as, end.duration_seconds
                )
                self._changed.notify_all()
        finally:
            _running_cells.release(self._tenant_id, time.monotonic() - self._started_at)

    def _print(self, text: str) -> None:
        with self._lock:
            live = self._stdout.write(text)
            if live:
                self._emit(CodeModeStdout(text=live))

    def _yield_control(self) -> None:
        """End the observation at the yield, so output after it goes to the next
        observation, however soon the observer wakes."""
        with self._lock:
            if self._observer is not None:
                self._yielded = self._take(self._observer, final=False)
                self._changed.notify_all()

    def _call(self, external: ExternalCall) -> object:
        function = self._program.stubs.functions[external.function_name]
        # The tool gets all of the arguments; the cell keeps a bounded copy.
        copied = tool_arguments(function, external.kwargs)
        # A dict: tool_arguments copies one.
        arguments = cast(dict[str, JsonValue], copied.value)
        started = CodeModeCall(
            index=external.index,
            id=f"{self._call_id}:{external.index}",
            tool_name=function.tool.name,
            tool_id=function.tool.id,
            function_name=function.function_name,
            arguments=_bounded_arguments(arguments, MAX_SAVED_CALL_CHARS, copied.text),
            state="running",
        )
        with self._lock:
            self._calls[external.index] = CellCallRecord(
                call=started, started_in=self._window
            )
            context = self._context.model_copy(
                update={
                    "chat_files": merged_chat_files(
                        self._context.chat_files, self._staged_files
                    )
                }
            )
            source = self._source
            self._emit(CodeModeCallStarted(call=started))
        try:
            return self._run_call(function, started, arguments, context, source)
        except AgentCancelled as error:
            # The program sees an error; the cell's end records the call as
            # unfinished.
            raise RuntimeError(CANCELLED_CALL_MESSAGE) from error
        except BeforeToolCallFailed as failed:
            # A policy failure: the program stops without seeing it, and the
            # observation that reports its end fails the run.
            with self._lock:
                if self._hook_failure is None:
                    self._hook_failure = failed
                self._record(
                    _bounded_call(started.failed(str(failed)), MAX_SAVED_CALL_CHARS)
                )
            self._stopping.cancel()
            raise
        except Exception as error:
            # The call ended with an exception, which the program sees.
            failed = started.failed(str(error) or type(error).__name__)
            with self._lock:
                if self._calls[external.index].ended_in is None:
                    self._record(_bounded_call(failed, MAX_SAVED_CALL_CHARS))
            raise
        finally:
            with self._lock:
                self._calls[external.index].thread_alive = False

    def _run_call(
        self,
        function: ToolFunction,
        started: CodeModeCall,
        arguments: dict[str, JsonValue],
        context: ToolContext,
        source: ToolInvocation,
    ) -> object:
        inner_tool = function.tool
        decided = _decided_result(source, started.id, inner_tool.name, arguments)
        cites = function.result.cites and decided is None
        start = (
            self._citations.reserve(context.next_citation_num)
            if cites
            else context.next_citation_num
        )
        used: dict[int, str] = {}
        try:
            if decided is not None:
                result = decided
            else:
                result = self._tool_result(
                    function, started, arguments, context, source, start
                )
            details = durable_details(result.details)
            if isinstance(details, SearchDocsResponse):
                used = dict(details.citation_mapping)
        finally:
            if cites:
                self._citations.release(used)
        if self._stages_files:
            known = {file.file_id for file in context.chat_files if file.file_id}
            staged = staged_result_details(
                result.details, known, build_python_chat_files_from_search_docs
            )
            if isinstance(staged, StagedChatFiles):
                with self._lock:
                    self._staged_files = merged_chat_files(
                        self._staged_files, staged.staged_files
                    )
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

    def _tool_result(
        self,
        function: ToolFunction,
        started: CodeModeCall,
        arguments: dict[str, JsonValue],
        context: ToolContext,
        source: ToolInvocation,
        citation_start: int,
    ) -> ToolResult:
        inner_tool = function.tool
        inner_context = context.model_copy(
            update={
                "next_citation_num": citation_start,
                "citation_mapping": {
                    **context.citation_mapping,
                    **self._citations.mapping(),
                },
            }
        )
        inner_invocation = ToolInvocation(
            call_id=started.id,
            call_index=0,
            arguments=arguments,
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
        with (
            sequential.turn(self._stopping)
            if sequential is not None
            else nullcontext(),
            cancellation_scope(self._stopping),
        ):
            return _call_result(inner_tool, inner_invocation, inner_context)

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
            history = _recorded_cell_ids(invocation.recorded_results)
            cell_id = max(self._highest_id, *history, 0) + 1
            snapshot = self._store.snapshot(invocation.recorded_results)
            cell = CodeCell(
                cell_id=cell_id,
                program=program,
                citations=self._citations,
                store=self._store,
                invocation=invocation,
                context=context,
            )
            # Only a cell that exists reports the dropped commits; one rejected
            # as busy leaves them for the next cell.
            self._store.reported(snapshot)
            self._highest_id = cell_id
            self._cells[cell_id] = cell
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
        first stop request (Stop or this call) to end. Raises `ReleaseFailed` with
        the records when the before_tool_call hook raised for a program's call
        and no observation reported it.
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
        amendments = [
            *amendments,
            *_interrupted_amendments(results, {cell.id for cell in cells}),
        ]
        # A hook failure that no observation raised fails the run, as for a
        # direct call; the first one wins.
        failures = [failure for cell in cells if (failure := cell.take_hook_failure())]
        if failures:
            raise ReleaseFailed(failures[0].error, amendments)
        return amendments
