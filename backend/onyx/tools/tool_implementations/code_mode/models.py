"""Typed details for code mode: one model-written program that calls other tools."""

import json
from collections.abc import Iterable, Mapping
from concurrent.futures import Future
from functools import cached_property
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic_monty import FunctionSnapshot, FutureSnapshot

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


class CodeModeCall(BaseModel):
    """One tool call made by the program, with the result the program received."""

    index: int
    # Tool call id: the id of the `execute_code` call that started the cell, then
    # `:<index>`. Traces, saved history and the UI all use it.
    id: str
    tool_name: str
    # Tool row of the called tool; the UI uses it to reconnect custom and MCP tools.
    tool_id: int | None = None
    # Name of the Python function the program called; differs when the tool name is not
    # a valid identifier.
    function_name: str
    arguments: dict[str, JsonValue]
    # Saved calls keep a bounded copy of the text; the program received all of it.
    content: str = ""
    state: CodeModeCallState
    details: CodeModeCallDetails | None = None

    @property
    def is_error(self) -> bool:
        return self.state in ("error", "unfinished")


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

    ordinal: int
    writes: dict[str, JsonValue]

    @cached_property
    def size_bytes(self) -> int:
        """Bytes the commit adds to the chat's saved history; measured once."""
        return sum(entry_bytes(key, value) for key, value in self.writes.items())


class CellWindow(BaseModel):
    """What a cell did in one time window."""

    stdout: str = ""
    # Calls that ended in the window, and calls still running at its end.
    calls: list[CodeModeCall] = Field(default_factory=list)
    # Set on the window in which the cell ended by itself with store() writes. Later
    # programs read the store as the fold of commits over the conversation, in
    # ordinal order (code_mode/store.py).
    commit: StoreCommit | None = None


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

    def windows(self) -> list[CellWindow]:
        """The observation's window, then its closing record's."""
        return [self] if self.closing is None else [self, self.closing]


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


# Compute time one program may use. The sandbox pool is shared by every program,
# so its parent-side request timeout backstops this limit for all of them.
MAX_CPU_SECONDS = 30.0


class SandboxLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Wall clock for one program, including the time its tool calls take.
    lifetime_seconds: float = 900.0
    max_tool_calls: int = 100
    # Characters of printed text, the result and the error collected for one
    # observation, cut in the middle; bounds host memory and the text that the
    # output budget tokenizes. About 16 times the default output budget.
    max_output_chars: int = 640_000
    max_memory_bytes: int = 128 * 1024 * 1024
    # Compute time inside the sandbox; time spent waiting for tools does not count.
    # At most MAX_CPU_SECONDS, which the shared pool's request timeout backstops.
    max_cpu_seconds: float = MAX_CPU_SECONDS


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
    # repr() of the final expression, when it is not None.
    result: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
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
    # Bytes of the commits saved in the conversation branch so far.
    committed_bytes: int = 0
    # The highest commit ordinal so far; 0 before the first commit.
    last_ordinal: int = 0
