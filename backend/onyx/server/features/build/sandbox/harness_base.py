"""The sandbox interface for an agent harness that runs outside the sandbox.

The harness (agent loop, LLM calls, event stream) runs in an Onyx process and
calls into the sandbox only through `HarnessSandbox`. One sandbox serves one
user; each chat session has its own directory in it
(`SESSION_WORKSPACE_ROOT/<session_id>`), which is the default working
directory. Commands are not confined to that directory.

Every call blocks the calling thread (agent runtime tools run in threads).
`exec_command` and `write_stdin` stream output as it arrives: iterate their
events and read the last one, an `ExecCommandResult`, or call
`collect_exec_result`.

Exec contract (Codex `exec_command` / `write_stdin`):
- `exec_command` starts a command and waits up to `yield_time_ms`. If the
  command ended, the result has its exit code. Otherwise it has an
  `exec_session_id` for `write_stdin`.
- `write_stdin` with no chars polls for new output. Chars go to the
  command's stdin. "\\x03" interrupts the command.
- Output of one call keeps at most `EXEC_CALL_OUTPUT_MAX_BYTES` (head and
  tail); the result text keeps at most `max_output_tokens` (head and tail).
- Exec session IDs stay valid across turns and API pods until the command's
  record is evicted, or the sandbox stops (idle stop, restore): then the call
  raises `ExecSessionEndedError`.
"""

import abc
from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Parent of each chat session's working directory in the sandbox.
SESSION_WORKSPACE_ROOT = "/home/onyx/workspaces"

EXEC_DEFAULT_YIELD_MS = 10_000
EXEC_MIN_YIELD_MS = 250
EXEC_MAX_YIELD_MS = 30_000
WRITE_STDIN_DEFAULT_YIELD_MS = 250
WRITE_STDIN_MAX_YIELD_MS = 30_000
# An empty write_stdin (a poll) waits at least this long for new output.
POLL_MIN_YIELD_MS = 5_000
POLL_MAX_YIELD_MS = 300_000
DEFAULT_MAX_OUTPUT_TOKENS = 10_000
EXEC_CALL_OUTPUT_MAX_BYTES = 1 << 20
# Most exec sessions per sandbox. Over the cap, the least recently used
# ended session goes first, then the least recently used running one.
MAX_EXEC_SESSIONS_PER_SANDBOX = 64

# The env of every command, so that tools write plain, unpaged UTF-8 text.
EXEC_DEFAULT_ENV: dict[str, str] = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "GH_PAGER": "cat",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}

INTERRUPT_CHAR = "\x03"


def session_workspace(session_id: UUID) -> str:
    return f"{SESSION_WORKSPACE_ROOT}/{session_id}"


class HarnessSandboxRef(BaseModel):
    """The sandbox of one user, seen from one chat session."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    sandbox_id: UUID
    session_id: UUID
    # Lower bound of the VM attempt (the Sandbox row's attempt number). The
    # running VM can have a higher attempt.
    attempt: int = Field(default=1, ge=1)


class ExecOutputDelta(BaseModel):
    """New output of a command (stdout and stderr in arrival order)."""

    model_config = ConfigDict(frozen=True)

    text: str


class ExecCommandResult(BaseModel):
    """The last event of `exec_command` and `write_stdin`."""

    model_config = ConfigDict(frozen=True)

    # Output of this call, cut to max_output_tokens (head and tail).
    output: str
    # Set while the command runs: pass it to write_stdin.
    exec_session_id: str | None
    # Set when the command exited. None while it runs, or when a signal,
    # an interrupt or its deadline ended it.
    exit_code: int | None
    # "exited", "signaled", "canceled" or "deadline_exceeded" after the end.
    completion: str | None
    wall_time_seconds: float
    # Estimated tokens of the output before the token cut.
    original_token_count: int
    # True when the byte or token cap removed output.
    truncated: bool

    @property
    def running(self) -> bool:
        return self.exec_session_id is not None


ExecEvent = ExecOutputDelta | ExecCommandResult


def collect_exec_result(events: Iterator[ExecEvent]) -> ExecCommandResult:
    """Drain an exec stream and return its result."""
    for event in events:
        if isinstance(event, ExecCommandResult):
            return event
    raise RuntimeError("The exec stream ended without a result")


class SandboxFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Relative to the session directory, "/"-separated.
    path: str
    name: str
    is_directory: bool
    size: int
    modified_at: datetime | None


class SandboxFileListing(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[SandboxFile]
    truncated: bool


class HarnessSandboxError(Exception):
    """A sandbox call failed in a way the model can read and act on."""


class ExecSessionNotFoundError(HarnessSandboxError):
    def __init__(self, exec_session_id: str) -> None:
        super().__init__(
            f"Unknown exec session {exec_session_id!r}: it was never started in "
            "this chat session, or it was evicted"
        )


class ExecSessionEndedError(HarnessSandboxError):
    def __init__(self, exec_session_id: str) -> None:
        super().__init__(
            f"Exec session {exec_session_id!r} ended: the sandbox restarted, "
            "and processes do not survive a restart. Run the command again."
        )


class SandboxPathError(HarnessSandboxError):
    """The path is outside the session directory or not valid."""


class SandboxFileTooLargeError(HarnessSandboxError):
    pass


class HarnessSandbox(abc.ABC):
    """What the harness calls. All methods block; see the module docstring."""

    @abc.abstractmethod
    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        """Start the sandbox if needed and return when it is ready (skills
        mounted, guest initialized). Every other call does this first."""

    @abc.abstractmethod
    def exec_command(
        self,
        ref: HarnessSandboxRef,
        cmd: str,
        *,
        workdir: str | None = None,
        yield_time_ms: int | None = None,
        max_output_tokens: int | None = None,
    ) -> Iterator[ExecEvent]:
        """Run `cmd` with bash in `workdir` (default: the session
        directory)."""

    @abc.abstractmethod
    def write_stdin(
        self,
        ref: HarnessSandboxRef,
        exec_session_id: str,
        chars: str = "",
        *,
        yield_time_ms: int | None = None,
        max_output_tokens: int | None = None,
    ) -> Iterator[ExecEvent]:
        """Write to a running command, or poll it with empty chars."""

    @abc.abstractmethod
    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        """Raises SandboxFileTooLargeError over max_bytes."""

    @abc.abstractmethod
    def write_file(self, ref: HarnessSandboxRef, path: str, data: bytes) -> None:
        """Atomic replace; creates parent directories."""

    @abc.abstractmethod
    def list_files(
        self, ref: HarnessSandboxRef, path: str = "", *, recursive: bool = False
    ) -> SandboxFileListing:
        pass

    @abc.abstractmethod
    def delete_file(
        self, ref: HarnessSandboxRef, path: str, *, recursive: bool = False
    ) -> bool:
        """False when the path did not exist."""

    @abc.abstractmethod
    def publish_artifact(
        self, ref: HarnessSandboxRef, path: str, *, display_name: str | None = None
    ) -> str:
        """Copy a session file to the file store. Returns the file ID."""

    @abc.abstractmethod
    def touch(self, ref: HarnessSandboxRef) -> None:
        """Record activity for the idle stop. Never starts the sandbox."""

    @abc.abstractmethod
    def begin_turn(self, ref: HarnessSandboxRef) -> None:
        """Mark a turn in progress (the sandbox is busy). Call again to
        renew; the mark expires on its own if end_turn never runs."""

    @abc.abstractmethod
    def end_turn(self, ref: HarnessSandboxRef) -> None:
        pass

    @abc.abstractmethod
    def set_approval_parked(self, ref: HarnessSandboxRef, parked: bool) -> None:
        """Mark or clear an approval that waits for the user (busy)."""

    @abc.abstractmethod
    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:
        """True while a command runs, a turn is in progress, or an approval
        waits. Never starts the sandbox."""
