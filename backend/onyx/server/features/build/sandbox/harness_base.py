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
from uuid import UUID

from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecEvent,
    HarnessSandboxRef,
)

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
# Most exec session records per sandbox; the least recently used goes
# first. The guest daemon caps the running commands.
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


def collect_exec_result(events: Iterator[ExecEvent]) -> ExecCommandResult:
    """Drain an exec stream and return its result. Reads the stream to its
    end, so the implementation releases what it holds."""
    result: ExecCommandResult | None = None
    for event in events:
        if isinstance(event, ExecCommandResult):
            result = event
    if result is None:
        raise RuntimeError("The exec stream ended without a result")
    return result


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


class ExecCapReachedError(HarnessSandboxError):
    def __init__(self) -> None:
        super().__init__(
            "Too many commands run in this sandbox. Stop one (write_stdin "
            'with "\\x03") or wait for one to end, then run the command again.'
        )


class SandboxPathError(HarnessSandboxError):
    """The path is outside the session directory."""


class SandboxFileTooLargeError(HarnessSandboxError):
    pass


class HarnessSandbox(abc.ABC):
    """What the harness calls. All methods block; see the module docstring."""

    @abc.abstractmethod
    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        """Start the sandbox if needed and return when the guest is
        initialized. Every other call does this first."""

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

    # Files: only what exec_command cannot do well. view_image needs exact
    # bytes (exec output is text), and apply_patch needs an exact write of
    # any content (no shell quoting). Listing, moving and deleting go
    # through exec_command.

    @abc.abstractmethod
    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        """Raises SandboxFileTooLargeError over max_bytes."""

    @abc.abstractmethod
    def write_file(self, ref: HarnessSandboxRef, path: str, data: bytes) -> None:
        """Atomic replace; creates parent directories."""

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
