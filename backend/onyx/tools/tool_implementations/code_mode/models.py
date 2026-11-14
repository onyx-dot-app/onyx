"""Typed details for code mode: one model-written program that calls other tools."""

import json
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future
from functools import cached_property
from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SerializeAsAny
from pydantic_monty import FunctionSnapshot, FutureSnapshot

from onyx.agents.tools import ToolInvocation
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.models import Message, ToolResultMessage
from onyx.tools.models import (
    CustomToolCallSummary,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.search.models import SearchPlanningResult

# Durable details of the tools that programs can call.
CodeModeCallDetails = Annotated[
    SearchDocsResponse
    | CustomToolCallSummary
    | FinalImageGenerationResponse
    | FileReadResult
    | LlmBashExecutionResult
    | LlmPythonExecutionResult
    | MemoryUpdated
    | ToolExecutionError,
    Field(discriminator="type"),
]
CODE_MODE_CALL_DETAIL_TYPES: tuple[type[BaseModel], ...] = get_args(
    get_args(CodeModeCallDetails)[0]
)


# How a program ended.
SandboxStatus = Literal["completed", "failed", "timed_out", "cancelled"]
# How a cell ended: `terminated` cells were stopped by wait_code or by the end of
# the response.
ClosedStatus = Literal[SandboxStatus, "terminated"]
# The state of a cell at the end of an observation: `running` cells continue.
CodeModeStatus = Literal[ClosedStatus, "running"]
# How a call ended: `running` calls had not ended when the observation ended;
# `unfinished` calls were still running when the program ended.
CodeModeCallState = Literal["running", "ok", "error", "unfinished"]
UNFINISHED_CALL_MESSAGE = "The call did not finish before the program ended."


class CodeModeCall(BaseModel):
    """One tool call made by the program, with the result the program received."""

    index: int
    # Tool call id: the id of the `execute_code` call that started the cell, then
    # `:<index>`. Traces, saved history and the UI all use it.
    id: str
    tool_name: str
    # Tool row of the called tool; the UI uses it to reconnect custom and MCP tools.
    tool_id: int | None = None
    # The called tool's display name. Calls saved without one show `tool_name`.
    display_name: str | None = None
    # Name of the Python function the program called; differs when the tool name is not
    # a valid identifier.
    function_name: str
    arguments: dict[str, JsonValue]
    # Saved calls keep a bounded copy of the text; the program received all of it.
    content: str = ""
    state: CodeModeCallState
    # Saved search details keep citation numbers but no documents;
    # chat/tool_results.py removes the documents on save and looks them up again on
    # restore.
    details: CodeModeCallDetails | None = None
    # Set while the turn runs: the planning decisions of a search call. Saving
    # (chat/tool_results.py) clears it.
    metadata: SearchPlanningResult | None = None
    # Set by saving a search (chat/tool_results.py): ids of the documents it
    # displayed, which are all its documents when it selected none. Restoring
    # rebuilds `details.displayed_docs` from them. None while the turn runs.
    displayed_document_ids: list[str] | None = None

    @property
    def is_error(self) -> bool:
        return self.state in ("error", "unfinished")

    def failed(self, message: str) -> "CodeModeCall":
        """This call, ended with an error; the error details make clients show it
        as failed."""
        return self.model_copy(
            update={
                "state": "error",
                "content": message,
                "details": ToolExecutionError(message=message),
            }
        )

    def unfinished(self) -> "CodeModeCall":
        """This call, recorded as still running when its program ended."""
        return self.failed(UNFINISHED_CALL_MESSAGE).model_copy(
            update={"state": "unfinished"}
        )

    def as_result(self) -> ToolResultMessage:
        """This call as the result of an ordinary tool call."""
        return ToolResultMessage(
            tool_call_id=self.id,
            tool_name=self.tool_name,
            content=self.content,
            details=self.details,
            is_error=self.is_error,
            metadata=self.metadata,
        )


def json_text(value: JsonValue) -> str:
    """Compact JSON of a stored value; the store measures and compares this."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def entry_bytes(key: str, value: JsonValue) -> int:
    """Bytes of a key and its JSON value; a deletion (None) counts its key only."""
    return len(key.encode("utf-8")) + (
        0 if value is None else len(json_text(value).encode("utf-8"))
    )


class StoreCommit(BaseModel):
    """The store() writes of one cell that ended by itself (completed, or stopped
    at an uncaught exception), None deleting the key, and the commit's place in
    the completion order of the conversation branch."""

    model_config = ConfigDict(frozen=True)

    ordinal: int
    # The ordinal of the last commit in the store that this commit was made
    # against; 0 for none. The store applies a commit only after that one.
    follows: int
    writes: Mapping[str, JsonValue]

    @cached_property
    def size_bytes(self) -> int:
        """Bytes of the values that the commit stores, which count toward the
        chat's limit on saved writes; measured once. Deleted keys do not count."""
        return sum(
            entry_bytes(key, value)
            for key, value in self.writes.items()
            if value is not None
        )


class LostStoreWrites(BaseModel):
    """Commits that the store dropped because the commit each one follows was
    never saved, as the first program after the drop reports them."""

    model_config = ConfigDict(frozen=True)

    # The highest ordinal of the dropped commits. The report covers every
    # dropped commit up to it, so its size does not grow with the commits.
    through: int
    # The keys that the dropped commits wrote, cut to a bounded length.
    keys: tuple[str, ...]
    # Keys left out of `keys` by the bound.
    more_keys: int = 0

    @property
    def note(self) -> str:
        keys = ", ".join(self.keys)
        more = f", and {self.more_keys} more" if self.more_keys else ""
        return (
            "Store writes of an earlier program were discarded because the "
            f"program before it did not finish saving its own: {keys}{more}. "
            "load() returns the values from before those writes."
        )


STOPPED_BEFORE_END = "the program was stopped before it ended"


class DiscardedWrites(BaseModel):
    """Keys of store() writes that did not commit, and why."""

    model_config = ConfigDict(frozen=True)

    keys: tuple[str, ...]
    reason: str

    @property
    def note(self) -> str | None:
        if not self.keys:
            return None
        return f"Store writes discarded because {self.reason}: {', '.join(self.keys)}."


class CellWindow(BaseModel):
    """What a cell did in one time window."""

    stdout: str = ""
    # Calls that ended in the window, and calls still running at its end.
    calls: list[CodeModeCall] = Field(default_factory=list)
    # Set on the window in which the cell ended by itself with store() writes. Later
    # programs read the store as the fold of commits over the conversation, in
    # ordinal order (code_mode/store.py).
    commit: StoreCommit | None = None
    # Calls the cell had started by the end of the window.
    tool_call_count: int = 0
    # Set on the window that reports the program's end. `result` is the repr()
    # of the JSON copy of the final expression, when it is not None; a value
    # that is not JSON data or is too large gives `error` instead.
    result: str | None = None
    error: str | None = None


# `suspended`: the run paused, for example to wait for a subagent.
# `interrupted`: the server stopped, so what the cell did after is not known.
CellClosingReason = Literal["response_ended", "suspended", "interrupted"]


class CellClosing(CellWindow):
    """What a cell did after its last observation, recorded when the response
    ended or the run paused."""

    reason: CellClosingReason
    status: ClosedStatus


class CodeModeExecutionResult(CellWindow):
    """Saved result of one observation of a cell (an `execute_code` or `wait_code`
    call); replay renders everything from it.

    Its window covers this observation; `closing` covers the cell after it.
    """

    type: Literal["code_mode_execution"] = "code_mode_execution"
    cell_id: int
    # 0 for the `execute_code` call that started the cell, then 1, 2, ...
    observation: int = 0
    # Set on observation 0 only.
    code: str = ""
    status: CodeModeStatus
    duration_seconds: float = 0.0
    # Set when the response ended after this observation reported a running cell.
    closing: CellClosing | None = None
    # Set on observation 0 of the first program after the store dropped commits.
    lost_store_writes: LostStoreWrites | None = None

    def windows(self) -> list[CellWindow]:
        """The observation's window, then its closing record's."""
        return [self] if self.closing is None else [self, self.closing]

    def all_calls(self) -> list[CodeModeCall]:
        """The calls of every window, in window order."""
        return [call for window in self.windows() for call in window.calls]

    def map_calls(self, transform: Callable[[CodeModeCall], CodeModeCall]) -> Self:
        """A copy with `transform` applied to the calls of every window."""
        closing = self.closing
        return self.model_copy(
            update={
                "calls": [transform(call) for call in self.calls],
                "closing": None
                if closing is None
                else closing.model_copy(
                    update={"calls": [transform(call) for call in closing.calls]}
                ),
            }
        )


def code_mode_results(
    messages: Iterable[Message],
) -> list[tuple[ToolResultMessage, CodeModeExecutionResult]]:
    """The saved code mode observations among `messages`, with their details."""
    return [
        (message, message.details)
        for message in messages
        if isinstance(message, ToolResultMessage)
        and isinstance(message.details, CodeModeExecutionResult)
    ]


# Progress details, sent through ToolInvocation.update while the program runs.
# They are not saved; the final CodeModeExecutionResult holds the same information.


class CodeModeCallStarted(BaseModel):
    """A call the program started; it has no result yet."""

    type: Literal["code_mode_call_started"] = "code_mode_call_started"
    call: CodeModeCall


class CodeModeCallProgress(BaseModel):
    """Progress details of an inner tool, forwarded unchanged."""

    type: Literal["code_mode_call_progress"] = "code_mode_call_progress"
    index: int
    content: str = ""
    details: SerializeAsAny[BaseModel] | None = None


class CodeModeCallFinished(BaseModel):
    type: Literal["code_mode_call_finished"] = "code_mode_call_finished"
    call: CodeModeCall


class CodeModeStdout(BaseModel):
    """New text the program printed."""

    type: Literal["code_mode_stdout"] = "code_mode_stdout"
    text: str


# What a cell reports to its observer while it runs.
CellEvent = (
    CodeModeCallStarted | CodeModeCallProgress | CodeModeCallFinished | CodeModeStdout
)


# Compute time one program may use. The sandbox pool is shared by every program,
# so its parent-side request timeout backstops this limit for all of them.
MAX_CPU_SECONDS = 30.0


class SandboxLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Wall clock for one program, including the time its tool calls take.
    lifetime_seconds: float = Field(default=900.0, gt=0)
    max_tool_calls: int = Field(default=100, gt=0)
    # Characters of printed text, the result and the error collected for one
    # observation, cut in the middle; bounds host memory and the text that the
    # output budget tokenizes. About 16 times the default output budget.
    max_output_chars: int = Field(default=640_000, gt=0)
    # Bytes of compact JSON in the host copy of the last expression's value;
    # bounds host memory before the copy's repr() is cut to max_output_chars.
    # UTF-8 uses at most 4 bytes per character.
    max_result_bytes: int = Field(default=4 * 640_000, gt=0)
    max_memory_bytes: int = Field(default=128 * 1024 * 1024, gt=0)
    # Compute time inside the sandbox; time spent waiting for tools does not count.
    # At most MAX_CPU_SECONDS, which the shared pool's request timeout backstops.
    max_cpu_seconds: float = Field(default=MAX_CPU_SECONDS, gt=0, le=MAX_CPU_SECONDS)


class ExternalCall(BaseModel):
    """A tool function call made by the program."""

    model_config = ConfigDict(frozen=True)

    # Order of the call within one execution, from 0.
    index: int
    function_name: str
    kwargs: dict[str, object]


class SandboxResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    # result and error each hold at most `max_output_chars`, cut in the middle.
    status: SandboxStatus
    # repr() of the JSON copy of the final expression, when it is not None. A
    # value that is not JSON data or is too large gives `error` instead.
    result: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    # Non-fatal type checker diagnostics, kept for failed executions.
    type_check_notes: str | None = None
    # The program's store() writes take effect: it completed, or stopped at an
    # exception it raised. A program that was stopped, timed out or did not start
    # does not commit.
    commits_store: bool = False
    # Tool calls not finished when the program completed without awaiting them.
    # They are not waited for; the caller cancels them.
    unawaited_calls: tuple[ExternalCall, ...] = ()
    # Tool calls the program never awaited that were still queued; they never run.
    unstarted_calls: tuple[ExternalCall, ...] = ()


class TypeDiagnostic(BaseModel):
    """One diagnostic line from the type checker."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    line: str


class PendingCall(BaseModel):
    """A tool call of the program that has not returned its result to it."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    external: ExternalCall
    # The call's thread; None while the call waits in the queue.
    future: Future[object] | None = None


class ProgramWaiting(BaseModel):
    """A program waiting on tool calls or sleeps, on its worker."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    state: FutureSnapshot | FunctionSnapshot

    @property
    def call_ids(self) -> list[int]:
        state = self.state
        if isinstance(state, FunctionSnapshot):
            return [state.call_id]
        return list(state.pending_call_ids)


class ProgramSuspended(BaseModel):
    """A waiting program dumped so that its worker could be returned; its bytes
    count against MAX_SUSPENDED_BYTES until it is loaded."""

    model_config = ConfigDict(frozen=True)

    snapshot: bytes
    call_ids: list[int]


class ProgramCompleted(BaseModel):
    model_config = ConfigDict(frozen=True)

    output: object


class ProgramStopped(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: SandboxStatus
    error: str
    # The program raised an exception that it did not catch.
    raised: bool = False


class StoreSnapshot(BaseModel):
    """The store after a set of commits."""

    model_config = ConfigDict(frozen=True)

    values: Mapping[str, JsonValue]
    # Bytes of the commits that the store applied in the conversation branch so
    # far; a commit dropped after a server stop does not count.
    committed_bytes: int = 0
    # The highest commit ordinal so far, applied or not; 0 before the first
    # commit. A new commit takes the next one.
    last_ordinal: int = 0
    # The ordinal of the last commit that `values` include; 0 for none.
    last_applied: int = 0
    # Commits the fold dropped that no saved observation reported yet, in
    # ordinal order.
    dropped: tuple[StoreCommit, ...] = ()


class StubParameter(BaseModel):
    """One argument of a tool function stub."""

    model_config = ConfigDict(frozen=True)

    python_name: str
    annotation: str
    # The schema requires the argument.
    required: bool
    # The schema accepts null for it. A required nullable argument is optional
    # in the stub and sent as null when a program leaves it out.
    nullable: bool
    description: str

    @property
    def has_default(self) -> bool:
        return not self.required or self.nullable


class StubResultType(BaseModel):
    """The return annotation of a tool function stub and the declarations of
    the types it names."""

    model_config = ConfigDict(frozen=True)

    annotation: str
    declarations: tuple[str, ...]


class SchemaRefBudget(BaseModel):
    """`$ref` resolutions spent while one stub types a JSON Schema."""

    total: int = 0


class SchemaType(BaseModel):
    """A JSON Schema as a Python type annotation, and whether it accepts null.

    One walk decides both, so a stub's type and how a call sends None agree.
    An annotation of Any can still accept null.
    """

    model_config = ConfigDict(frozen=True)

    annotation: str
    nullable: bool


class SearchableFunction(BaseModel):
    """A deferred function as tool_search() matches and returns it."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    # The function's stub with the declarations of its result types.
    stub: str
    # Text that the search matches: the name (weighted), namespace and description.
    text: str


class CellCallRecord(BaseModel):
    """A nested call of a cell."""

    # As started, then as it ended (bounded).
    call: CodeModeCall
    # The windows in which the call started and ended; None while it runs.
    started_in: int
    ended_in: int | None = None
    # The call's thread has not returned; a call can ignore cancellation.
    thread_alive: bool = True

    def in_window(self, window: int) -> bool:
        """Whether the window reports the call: it ended in it, or still runs."""
        return self.ended_in is None or self.ended_in == window


class CellObserver(BaseModel):
    """The tool call that observes a cell."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    invocation: ToolInvocation
    number: int
    # Tokens of output that the observation returns.
    max_tokens: int


class ObservationCut(BaseModel):
    """An ended observation, taken under the cell lock and formatted after it, so
    tokenizing large output does not hold up the cell."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    # The parts as collected; `saved` holds them cut for saving.
    details: CodeModeExecutionResult
    saved: CodeModeExecutionResult
    max_tokens: int
    # Every call of the cell, earlier observations' included, in index order.
    cell_calls: list[CodeModeCall]
    # Set when the observation reports the program's end.
    end: SandboxResult | None
    discarded: DiscardedWrites | None
    elided_chars: int
