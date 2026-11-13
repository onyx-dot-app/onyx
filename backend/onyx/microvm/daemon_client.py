"""Typed client for the guest daemon (`craft.sandboxd.v1.Sandboxd`), through the
host agent pass-through.

The API is `microvm/proto/sandboxd/v1/sandboxd.proto`. Every call carries
`x-sandbox-id` (the agent routes on it). Every call except Health, Init
included, also carries the VM's key in `x-sandboxd-key`. The agent installs
the key at Create; this client never calls SetKey.

Errors: a daemon error is a `SandboxDaemonError` (domain
`sandboxd.craft.onyx.app`). An error of the pass-through itself (the VM is not
running, the daemon is unreachable) is a `HostAgentError`.
"""

import hashlib
import secrets
import threading
from collections.abc import Generator, Iterator
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, TypeVar

import grpc
from pydantic import SecretStr

from onyx.microvm.agent_client import (
    HostAgentError,
    error_info,
    host_agent_error,
    proto_time,
)
from onyx.microvm.configs import SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2, sandboxd_pb2_grpc
from onyx.microvm.models import (
    CancelResult,
    CancelSignal,
    DaemonHealth,
    DaemonInitResult,
    ExecCommand,
    ExecCompletion,
    ExecEvent,
    ExecGap,
    ExecOutput,
    ExecResult,
    ExecStarted,
    ExecState,
    ExecutionRecord,
    FileEntry,
    FileListing,
    FileType,
    OutputStream,
    WrittenFile,
    ZipSummary,
)

SANDBOXD_ERROR_DOMAIN = "sandboxd.craft.onyx.app"
SANDBOX_ID_HEADER = "x-sandbox-id"
SANDBOXD_KEY_HEADER = "x-sandboxd-key"
# Init attaches drives and grows the scratch file system.
_INIT_TIMEOUT_SECONDS = max(SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS, 60.0)
_ENTROPY_BYTES = 64
# The daemon's default command deadline when Command.deadline is not set.
_DEFAULT_EXEC_DEADLINE_SECONDS = 30 * 60.0
# Run and Stream end with the result; the gRPC deadline only bounds a lost stream.
_STREAM_MARGIN_SECONDS = 60.0
# The agent resets a stream at its deadline with CANCELLED, and that reset can
# arrive before the client's own deadline fires. A stream window therefore
# ends on the client first, well before the deadline it sends.
_WINDOW_MARGIN_SECONDS = 5.0
# File transfers and zips of up to the daemon's --max-file-bytes (1 GiB).
_TRANSFER_TIMEOUT_SECONDS = max(SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS, 600.0)
# WriteFile/UploadFile data messages (the daemon accepts up to 4 MiB).
_WRITE_CHUNK_BYTES = 1 << 20


class SandboxDaemonErrorReason(str, Enum):
    """`ErrorReason` names from sandboxd.proto."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
    STDIN_NOT_OPEN = "STDIN_NOT_OPEN"
    EXECUTION_ENDED = "EXECUTION_ENDED"
    START_FAILED = "START_FAILED"
    TOO_MANY_EXECUTIONS = "TOO_MANY_EXECUTIONS"
    INIT_FAILED = "INIT_FAILED"
    INTERNAL = "INTERNAL"
    KEY_NOT_SET = "KEY_NOT_SET"
    KEY_ALREADY_SET = "KEY_ALREADY_SET"
    MANAGED_SLOT_BUSY = "MANAGED_SLOT_BUSY"
    MANAGED_DEVICE_MISMATCH = "MANAGED_DEVICE_MISMATCH"
    MANAGED_MOUNT_FAILED = "MANAGED_MOUNT_FAILED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_EXISTS = "FILE_EXISTS"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    ARCHIVE_INVALID = "ARCHIVE_INVALID"
    EXECUTION_CAP_REACHED = "EXECUTION_CAP_REACHED"


# The daemon will not accept this VM's key: nothing can use the VM.
_UNUSABLE_REASONS: frozenset[SandboxDaemonErrorReason] = frozenset(
    {SandboxDaemonErrorReason.KEY_NOT_SET, SandboxDaemonErrorReason.UNAUTHENTICATED}
)


class SandboxDaemonError(Exception):
    def __init__(
        self,
        code: grpc.StatusCode,
        message: str,
        reason: SandboxDaemonErrorReason,
    ) -> None:
        super().__init__(f"{reason.value}: {message}")
        self.code = code
        self.message = message
        self.reason = reason

    @property
    def vm_unusable(self) -> bool:
        """True when the daemon has no key or another key. Stop the VM and
        create a new attempt."""
        return self.reason in _UNUSABLE_REASONS


class SandboxDaemonKeyNotSetError(SandboxDaemonError):
    """The agent did not install a key: the VM is unusable."""


def _protocol_error(message: str) -> SandboxDaemonError:
    """The daemon answered out of the proto's message order."""
    return SandboxDaemonError(
        grpc.StatusCode.INTERNAL, message, SandboxDaemonErrorReason.INTERNAL
    )


def sandbox_daemon_error(err: grpc.RpcError) -> SandboxDaemonError | HostAgentError:
    """The typed error of a failed daemon call. Host agent session saves use it
    too: they pass guest daemon errors through."""
    info = error_info(err)
    if (
        info is None
        or info.domain != SANDBOXD_ERROR_DOMAIN
        or not isinstance(err, grpc.Call)
    ):
        # The pass-through's own error, or no answer.
        return host_agent_error(err, info)
    try:
        reason = SandboxDaemonErrorReason(info.reason)
    except ValueError:
        reason = SandboxDaemonErrorReason.INTERNAL
    cls = (
        SandboxDaemonKeyNotSetError
        if reason is SandboxDaemonErrorReason.KEY_NOT_SET
        else SandboxDaemonError
    )
    return cls(err.code(), err.details() or "", reason)


_OUTPUT_STREAMS: dict[int, OutputStream] = {
    sandboxd_pb2.STDOUT: OutputStream.STDOUT,
    sandboxd_pb2.STDERR: OutputStream.STDERR,
}

_CANCEL_SIGNALS: dict[CancelSignal, sandboxd_pb2.CancelSignal] = {
    CancelSignal.SIGKILL: sandboxd_pb2.CANCEL_SIGNAL_SIGKILL,
    CancelSignal.SIGINT: sandboxd_pb2.CANCEL_SIGNAL_SIGINT,
    CancelSignal.SIGTERM: sandboxd_pb2.CANCEL_SIGNAL_SIGTERM,
}

_COMPLETIONS: dict[int, ExecCompletion] = {
    sandboxd_pb2.EXITED: ExecCompletion.EXITED,
    sandboxd_pb2.SIGNALED: ExecCompletion.SIGNALED,
    sandboxd_pb2.CANCELED: ExecCompletion.CANCELED,
    sandboxd_pb2.DEADLINE_EXCEEDED: ExecCompletion.DEADLINE_EXCEEDED,
}

_EXEC_STATES: dict[int, ExecState] = {
    sandboxd_pb2.RUNNING: ExecState.RUNNING,
    sandboxd_pb2.ENDED: ExecState.ENDED,
}

_FILE_TYPES: dict[int, FileType] = {
    sandboxd_pb2.FILE_TYPE_REGULAR: FileType.REGULAR,
    sandboxd_pb2.FILE_TYPE_DIRECTORY: FileType.DIRECTORY,
    sandboxd_pb2.FILE_TYPE_SYMLINK: FileType.SYMLINK,
    sandboxd_pb2.FILE_TYPE_OTHER: FileType.OTHER,
}


def _command_proto(command: ExecCommand) -> sandboxd_pb2.Command:
    proto = sandboxd_pb2.Command(
        argv=command.argv,
        cwd=command.cwd,
        env=command.env,
        stdin=command.stdin,
        labels=command.labels,
        session_id=command.session_id,
    )
    if command.deadline_seconds is not None:
        proto.deadline.FromNanoseconds(int(command.deadline_seconds * 1e9))
    return proto


def _started(msg: sandboxd_pb2.ExecStarted) -> ExecStarted:
    return ExecStarted(
        execution_id=msg.execution_id,
        pid=msg.pid,
        started_at=proto_time(msg, "started_at"),
        deadline_at=proto_time(msg, "deadline_at"),
    )


def _result(msg: sandboxd_pb2.ExecResult) -> ExecResult:
    return ExecResult(
        completion=_COMPLETIONS.get(msg.completion, ExecCompletion.UNSPECIFIED),
        exit_code=msg.exit_code,
        signal=msg.signal,
        finished_at=proto_time(msg, "finished_at"),
        stdout_bytes=msg.stdout_bytes,
        stderr_bytes=msg.stderr_bytes,
    )


def _exec_event(msg: sandboxd_pb2.ExecEvent) -> ExecEvent | None:
    kind = msg.WhichOneof("event")
    if kind == "started":
        return _started(msg.started)
    if kind == "output":
        stream = _OUTPUT_STREAMS.get(msg.output.stream)
        if stream is None:
            return None
        return ExecOutput(stream=stream, offset=msg.output.offset, data=msg.output.data)
    if kind == "gap":
        stream = _OUTPUT_STREAMS.get(msg.gap.stream)
        if stream is None:
            return None
        # "from" is a Python keyword.
        start = getattr(msg.gap, "from")  # ods: ignore[getattr]
        return ExecGap(stream=stream, start=start, end=msg.gap.to)
    if kind == "result":
        return _result(msg.result)
    return None


def _execution(msg: sandboxd_pb2.Execution) -> ExecutionRecord:
    return ExecutionRecord(
        execution_id=msg.execution_id,
        state=_EXEC_STATES.get(msg.state, ExecState.UNSPECIFIED),
        argv=list(msg.argv),
        labels=dict(msg.labels),
        pid=msg.pid,
        started_at=proto_time(msg, "started_at"),
        deadline_at=proto_time(msg, "deadline_at"),
        stdout_bytes=msg.stdout_bytes,
        stderr_bytes=msg.stderr_bytes,
        result=_result(msg.result) if msg.HasField("result") else None,
    )


def _file_entry(msg: sandboxd_pb2.FileInfo) -> FileEntry:
    return FileEntry(
        path=msg.path,
        name=msg.name,
        type=_FILE_TYPES.get(msg.type, FileType.UNSPECIFIED),
        size=msg.size,
        mode=msg.mode,
        modified_at=proto_time(msg, "modified_at"),
        link_target=msg.link_target,
    )


def _chunks(data: bytes) -> Iterator[bytes]:
    for start in range(0, len(data), _WRITE_CHUNK_BYTES):
        yield data[start : start + _WRITE_CHUNK_BYTES]


_Msg_co = TypeVar("_Msg_co", covariant=True)


class _ResponseStream(Protocol[_Msg_co]):
    """A server-streaming gRPC call: an iterator of messages that can be
    cancelled. Dropping it also cancels the call."""

    def __iter__(self) -> Iterator[_Msg_co]: ...

    def __next__(self) -> _Msg_co: ...

    def cancel(self) -> bool: ...


class SandboxDaemonClient:
    """The guest daemon of one VM. Shares the agent's channel; never closes it."""

    def __init__(
        self, channel: grpc.Channel, *, sandbox_id: str, sandboxd_key: SecretStr
    ) -> None:
        self._stub = sandboxd_pb2_grpc.SandboxdStub(channel)
        self._sandbox_id = sandbox_id
        self._key = sandboxd_key

    def _routing(self) -> tuple[tuple[str, str], ...]:
        return ((SANDBOX_ID_HEADER, self._sandbox_id),)

    def _authed(self) -> tuple[tuple[str, str], ...]:
        return (
            (SANDBOX_ID_HEADER, self._sandbox_id),
            (SANDBOXD_KEY_HEADER, self._key.get_secret_value()),
        )

    def health(self, timeout: float | None = None) -> DaemonHealth:
        """Needs no key."""
        try:
            r: sandboxd_pb2.HealthResponse = self._stub.Health(
                sandboxd_pb2.HealthRequest(),
                metadata=self._routing(),
                timeout=(
                    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS if timeout is None else timeout
                ),
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return DaemonHealth(
            initialized=r.initialized,
            key_set=r.key_set,
            version=r.version,
            generation=r.generation,
            sandbox_id=r.sandbox_id,
            running_executions=r.running_executions,
        )

    def init(
        self,
        *,
        generation: int,
        scratch_gib: int,
        env: dict[str, str],
        session_ids: list[str],
    ) -> DaemonInitResult:
        """Run after every boot or restore, after the agent's CloseConnections.

        Raises SandboxDaemonError; `vm_unusable` is True on KEY_NOT_SET.
        """
        request = sandboxd_pb2.InitRequest(
            entropy=secrets.token_bytes(_ENTROPY_BYTES),
            env=env,
            session_ids=session_ids,
            generation=generation,
            sandbox_id=self._sandbox_id,
            scratch_bytes=scratch_gib << 30,
        )
        request.host_time.FromDatetime(datetime.now(timezone.utc))
        try:
            r: sandboxd_pb2.InitResponse = self._stub.Init(
                request, metadata=self._authed(), timeout=_INIT_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return DaemonInitResult(
            version=r.version,
            clock_step_seconds=r.clock_step.ToTimedelta().total_seconds(),
            entropy_credited=r.entropy_credited,
            attached=r.attached,
            relay_reset=r.relay_reset,
        )

    # Exec. A command that ends in any way is an ExecResult, not an error.

    def _exec_events(
        self, call: _ResponseStream[sandboxd_pb2.ExecEvent]
    ) -> Generator[ExecEvent, None, None]:
        try:
            for msg in call:
                event = _exec_event(msg)
                if event is None:
                    continue
                yield event
                if isinstance(event, ExecResult):
                    return
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        finally:
            call.cancel()
        raise _protocol_error("the exec stream ended without a result")

    def run(self, command: ExecCommand) -> Generator[ExecEvent, None, None]:
        """Run a command and stream its events: ExecStarted, output and gaps,
        then the ExecResult.

        The command starts when the iterator is first read. If the stream
        breaks or the iterator is closed, the command keeps running: resume
        with `stream()` and the execution ID of the first event. Errors (for
        example START_FAILED) raise from the iterator.
        """
        deadline = command.deadline_seconds or _DEFAULT_EXEC_DEADLINE_SECONDS
        call: _ResponseStream[sandboxd_pb2.ExecEvent] = self._stub.Run(
            sandboxd_pb2.RunRequest(command=_command_proto(command)),
            metadata=self._authed(),
            timeout=deadline + _STREAM_MARGIN_SECONDS,
        )
        yield from self._exec_events(call)

    def start(self, command: ExecCommand) -> ExecStarted:
        """Start a command in the background."""
        try:
            r: sandboxd_pb2.StartResponse = self._stub.Start(
                sandboxd_pb2.StartRequest(command=_command_proto(command)),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return _started(r.started)

    def stream(
        self,
        execution_id: str,
        *,
        stdout_offset: int = 0,
        stderr_offset: int = 0,
        window_seconds: float | None = None,
    ) -> Generator[ExecEvent, None, None]:
        """Stream an execution's output from the offsets, then its result.
        Works while it runs and after it ended. A gap event marks bytes the
        daemon no longer keeps. The call starts when the iterator is first
        read. With `window_seconds`, the stream ends without a result when
        the window passes; the command keeps running."""
        if window_seconds is None:
            timeout = _DEFAULT_EXEC_DEADLINE_SECONDS + _STREAM_MARGIN_SECONDS
        else:
            timeout = window_seconds + _WINDOW_MARGIN_SECONDS
        call: _ResponseStream[sandboxd_pb2.ExecEvent] = self._stub.Stream(
            sandboxd_pb2.StreamRequest(
                execution_id=execution_id,
                stdout_offset=stdout_offset,
                stderr_offset=stderr_offset,
            ),
            metadata=self._authed(),
            timeout=timeout,
        )
        if window_seconds is None:
            yield from self._exec_events(call)
            return
        window_ended = threading.Event()

        def end_window() -> None:
            window_ended.set()
            call.cancel()

        timer = threading.Timer(window_seconds, end_window)
        timer.daemon = True
        timer.start()
        try:
            yield from self._exec_events(call)
        except HostAgentError as e:
            ended = (
                window_ended.is_set() and e.code is grpc.StatusCode.CANCELLED
            ) or e.code is grpc.StatusCode.DEADLINE_EXCEEDED
            if e.reached_agent or not ended:
                raise
        finally:
            timer.cancel()

    def interact(
        self, execution_id: str, *, data: bytes = b"", close_stdin: bool = False
    ) -> int:
        """Write to the stdin of a command started with stdin=True. Returns
        the bytes written. STDIN_NOT_OPEN / EXECUTION_ENDED raise."""
        try:
            r: sandboxd_pb2.InteractResponse = self._stub.Interact(
                sandboxd_pb2.InteractRequest(
                    execution_id=execution_id, data=data, close_stdin=close_stdin
                ),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return r.written

    def cancel(
        self, execution_id: str, signal: CancelSignal = CancelSignal.SIGKILL
    ) -> CancelResult:
        """SIGKILL: kill the execution's cgroup; the result is CANCELED.
        SIGINT/SIGTERM (Ctrl-C): signal the main process's group and return
        without a result. An ended execution returns its own result."""
        try:
            r: sandboxd_pb2.CancelResponse = self._stub.Cancel(
                sandboxd_pb2.CancelRequest(
                    execution_id=execution_id, signal=_CANCEL_SIGNALS[signal]
                ),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return CancelResult(
            result=_result(r.result) if r.HasField("result") else None,
            already_ended=r.already_ended,
            signaled=r.signaled,
        )

    def inspect(self, execution_id: str) -> ExecutionRecord:
        try:
            r: sandboxd_pb2.InspectResponse = self._stub.Inspect(
                sandboxd_pb2.InspectRequest(execution_id=execution_id),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return _execution(r.execution)

    def list_executions(
        self, labels: dict[str, str] | None = None
    ) -> list[ExecutionRecord]:
        """Every execution record that has all `labels`."""
        try:
            r: sandboxd_pb2.ListResponse = self._stub.List(
                sandboxd_pb2.ListRequest(labels=labels or {}),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return [_execution(x) for x in r.executions]

    # Files. Paths are relative to /home/onyx/workspaces/<session_id>/; with
    # session_id="" they are absolute VM paths (not upload or saves).

    def read_file(
        self, *, session_id: str, path: str, offset: int = 0, length: int = 0
    ) -> tuple[FileEntry, Iterator[bytes]]:
        """The file's info and its bytes from `offset` (length 0 = to the
        end), in chunks of at most 64 KiB. FILE_NOT_FOUND raises here.
        Closing or dropping the chunk iterator cancels the stream."""
        call: _ResponseStream[sandboxd_pb2.ReadFileResponse] = self._stub.ReadFile(
            sandboxd_pb2.ReadFileRequest(
                session_id=session_id, path=path, offset=offset, length=length
            ),
            metadata=self._authed(),
            timeout=_TRANSFER_TIMEOUT_SECONDS,
        )
        try:
            first: sandboxd_pb2.ReadFileResponse = next(call)
        except grpc.RpcError as e:
            call.cancel()
            raise sandbox_daemon_error(e) from e
        except StopIteration:
            raise _protocol_error("ReadFile ended without the file info") from None
        if first.WhichOneof("part") != "info":
            call.cancel()
            raise _protocol_error("ReadFile did not start with the file info")
        return _file_entry(first.info), self._read_chunks(call)

    def _read_chunks(
        self, call: _ResponseStream[sandboxd_pb2.ReadFileResponse]
    ) -> Iterator[bytes]:
        try:
            for msg in call:
                if msg.WhichOneof("part") == "data":
                    yield msg.data
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        finally:
            call.cancel()

    def write_file(
        self,
        *,
        session_id: str,
        path: str,
        data: bytes,
        mode: int = 0,
        overwrite: bool = True,
        make_parents: bool = True,
    ) -> WrittenFile:
        """Atomic write: the daemon renames the file into place only when the
        size and SHA-256 match. Without overwrite, FILE_EXISTS raises."""
        header = sandboxd_pb2.WriteFileHeader(
            session_id=session_id,
            path=path,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            mode=mode,
            overwrite=overwrite,
            make_parents=make_parents,
        )

        def requests() -> Iterator[sandboxd_pb2.WriteFileRequest]:
            yield sandboxd_pb2.WriteFileRequest(header=header)
            for chunk in _chunks(data):
                yield sandboxd_pb2.WriteFileRequest(data=chunk)

        try:
            r: sandboxd_pb2.WriteFileResponse = self._stub.WriteFile(
                requests(), metadata=self._authed(), timeout=_TRANSFER_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return WrittenFile(info=_file_entry(r.info), sha256=r.sha256)

    def upload_file(
        self, *, session_id: str, file_name: str, data: bytes, directory: str = ""
    ) -> WrittenFile:
        """Store an upload under a free name in `directory` (default
        attachments). `info.path` is the stored path."""
        header = sandboxd_pb2.UploadFileHeader(
            session_id=session_id,
            file_name=file_name,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            directory=directory,
        )

        def requests() -> Iterator[sandboxd_pb2.UploadFileRequest]:
            yield sandboxd_pb2.UploadFileRequest(header=header)
            for chunk in _chunks(data):
                yield sandboxd_pb2.UploadFileRequest(data=chunk)

        try:
            r: sandboxd_pb2.UploadFileResponse = self._stub.UploadFile(
                requests(), metadata=self._authed(), timeout=_TRANSFER_TIMEOUT_SECONDS
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return WrittenFile(info=_file_entry(r.info), sha256=r.sha256)

    def list_files(
        self,
        *,
        session_id: str,
        path: str = "",
        recursive: bool = False,
        max_depth: int = 0,
        exclude_names: list[str] | None = None,
        skip_hidden: bool = False,
        max_entries: int = 0,
    ) -> FileListing:
        """One directory (empty path = the session directory), or the tree
        with recursive. 0 limits mean the daemon defaults."""
        try:
            r: sandboxd_pb2.ListFilesResponse = self._stub.ListFiles(
                sandboxd_pb2.ListFilesRequest(
                    session_id=session_id,
                    path=path,
                    recursive=recursive,
                    max_depth=max_depth,
                    exclude_names=exclude_names or [],
                    skip_hidden=skip_hidden,
                    max_entries=max_entries,
                ),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return FileListing(
            entries=[_file_entry(x) for x in r.entries], truncated=r.truncated
        )

    def delete_file(
        self, *, session_id: str, path: str, recursive: bool = False
    ) -> bool:
        """Remove a file or link, or a directory with recursive. Returns
        False when the path did not exist."""
        try:
            r: sandboxd_pb2.DeleteFileResponse = self._stub.DeleteFile(
                sandboxd_pb2.DeleteFileRequest(
                    session_id=session_id, path=path, recursive=recursive
                ),
                metadata=self._authed(),
                timeout=SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        return r.deleted

    def zip_files(
        self,
        *,
        session_id: str,
        path: str,
        exclude_names: list[str] | None = None,
        skip_hidden: bool = False,
    ) -> Generator[bytes, None, ZipSummary]:
        """Yield the bytes of a deflate zip of the regular files under
        `path`; the generator returns the summary. On an error (for example
        LIMIT_EXCEEDED) drop the bytes received so far."""
        call: _ResponseStream[sandboxd_pb2.ZipFilesResponse] = self._stub.ZipFiles(
            sandboxd_pb2.ZipFilesRequest(
                session_id=session_id,
                path=path,
                exclude_names=exclude_names or [],
                skip_hidden=skip_hidden,
            ),
            metadata=self._authed(),
            timeout=_TRANSFER_TIMEOUT_SECONDS,
        )
        try:
            for msg in call:
                part = msg.WhichOneof("part")
                if part == "data":
                    yield msg.data
                elif part == "summary":
                    return ZipSummary(
                        files=msg.summary.files,
                        input_bytes=msg.summary.input_bytes,
                        zip_bytes=msg.summary.zip_bytes,
                        skipped=msg.summary.skipped,
                    )
        except grpc.RpcError as e:
            raise sandbox_daemon_error(e) from e
        finally:
            call.cancel()
        raise _protocol_error("ZipFiles ended without a summary")
