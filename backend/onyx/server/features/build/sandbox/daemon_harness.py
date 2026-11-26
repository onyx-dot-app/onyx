"""The `HarnessSandbox` logic shared by backends that run the guest daemon
(sandboxd) in each sandbox instance.

All calls go to `SandboxDaemonClient` (exec records, stdin, Stop, files,
`stat_files`, skills, renders, session setup and purges). A backend
supplies the running instance and its lifecycle through the hooks:
`_instance` (start if needed), `_instance_if_running`, `_transfer` (session
saves), `_mark_session_set_up`, `_stop` and `_forget_sandbox` (purge), and
`touch`. An instance is `(attempt, generation)`: exec records and session
setup belong to one instance, so a restart ends them.
"""

import abc
import io
import posixpath
import secrets
import tarfile
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from typing import IO
from uuid import UUID, uuid4

import grpc

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.llm.cancellation import (
    CancellationSignal,
    check_cancelled,
    current_cancellation,
)
from onyx.microvm.agent_client import HostAgentError
from onyx.microvm.daemon_client import (
    STAT_FILES_MAX_PATH_BYTES,
    STAT_FILES_MAX_PATHS,
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.models import (
    CancelSignal,
    ExecCommand,
    ExecCompletion,
    ExecGap,
    ExecOutput,
    ExecResult,
    ExecStarted,
    FileListing,
    FileType,
    OutputStream,
    PathStat,
    StatError,
)
from onyx.server.features.build.sandbox.exec_output import (
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
    ExecOutputBuffer,
)
from onyx.server.features.build.sandbox.file_copy_state import (
    COPY_STATE_SECONDS,
    copy_generation_key,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    EXEC_SESSIONS_PREFIX,
    SANDBOX_STATE_PREFIXES,
    SAVED_SESSIONS_PREFIX,
    SESSION_INSTANCES_PREFIX,
    forget_session_on_instances,
    get_exec_session,
    get_ids,
    get_session_save,
    has_marks,
    has_session_records,
    is_purged,
    mark_purged,
    note_wanted,
    put_exec_session,
    remove_exec_session,
    sessions_on_instance,
    set_mark,
)
from onyx.server.features.build.sandbox.firecracker.models import (
    ExecSessionRecord,
    ExecSessionTable,
    SessionInstanceTable,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    ArchiveStorage,
    BackgroundTurnSave,
    SessionSaveError,
    SessionTransfer,
    delete_session_archives,
    restore_session,
    save_session,
    session_save_lock,
    tenant_scope,
)
from onyx.server.features.build.sandbox.harness_base import (
    INTERRUPT_CHAR,
    ONYX_VM_FILES_ROOT,
    RENDER_PREVIEW_MAX_OUTPUT_BYTES,
    RENDER_PREVIEW_MAX_PDF_BYTES,
    RENDER_PREVIEW_ROOT,
    RENDER_PREVIEW_SIZE_PX,
    RENDER_PREVIEW_SUFFIXES,
    ExecCapReachedError,
    ExecSessionEndedError,
    ExecSessionNotFoundError,
    HarnessSandbox,
    HarnessSandboxError,
    RenderBudgetSpentError,
    SandboxFileNotFoundError,
    SandboxFileTooLargeError,
    SandboxPathError,
    SessionFiles,
    onyx_vm_path,
    session_relative_path,
    session_tool_results,
)
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecCompletionName,
    ExecEvent,
    ExecOutputDelta,
    FileSet,
    HarnessSandboxKey,
    HarnessSandboxRef,
    RenderedPreview,
    RenderFileBytes,
    RenderSessionFile,
    SandboxFileType,
    SandboxPathFault,
    SandboxPathInfo,
    session_workspace,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Deadline of one command. Background servers need a long one; the guest
# daemon caps it at 24 h.
EXEC_DEADLINE_SECONDS = 4 * 3600.0
# A turn mark expires after this long without a renewal (begin_turn).
TURN_LEASE_SECONDS = 15 * 60.0
# A parked approval keeps the sandbox busy for at most this long.
APPROVAL_PARK_SECONDS = 24 * 3600.0
# A session's restore runs once per instance across API pods; it covers a
# restore at the agent's 15 min transfer deadline.
_SESSION_SETUP_LOCK_PREFIX = "sandbox_fc:session_setup:"
_SESSION_SETUP_LOCK_SECONDS = 30 * 60.0
# Client token on each started command, to find it when Start gets no answer.
_START_LABEL = "onyx_start_id"
# The daemon refuses Start and Run with these while it keeps its most commands.
_EXEC_CAP_REASONS = frozenset(
    {
        SandboxDaemonErrorReason.EXECUTION_CAP_REACHED,
        SandboxDaemonErrorReason.TOO_MANY_EXECUTIONS,
    }
)
_COMPLETION_NAMES: dict[ExecCompletion, ExecCompletionName] = {
    ExecCompletion.EXITED: "exited",
    ExecCompletion.SIGNALED: "signaled",
    ExecCompletion.CANCELED: "canceled",
    ExecCompletion.DEADLINE_EXCEEDED: "deadline_exceeded",
}
_SANDBOX_FILE_TYPES: dict[FileType, SandboxFileType] = {
    FileType.REGULAR: "file",
    FileType.DIRECTORY: "directory",
    FileType.OTHER: "other",
}
# The tail of a failed render command's output that its log keeps.
_RENDER_LOG_OUTPUT_BYTES = 2000
_STAT_ERRORS: dict[StatError, SandboxPathFault] = {
    StatError.ESCAPES: "escapes",
    StatError.LOOP: "loop",
    StatError.OTHER: "other",
}


class RunningInstance:
    """A running sandbox instance: its guest daemon and its identity. A
    plain class, since a backend adds its own handles (for example the
    placed VM) that are not data."""

    def __init__(
        self, *, daemon: SandboxDaemonClient, attempt: int, generation: int
    ) -> None:
        self.daemon = daemon
        self.attempt = attempt
        self.generation = generation

    @property
    def identity(self) -> tuple[int, int]:
        return (self.attempt, self.generation)


def _find_started(
    daemon: SandboxDaemonClient, start_label: dict[str, str]
) -> str | None:
    """The execution of a Start whose response was lost, if it started."""
    try:
        found = daemon.list_executions(start_label)
    except (HostAgentError, SandboxDaemonError):
        logger.warning("sandbox_fc_start_reconcile_failed", exc_info=True)
        return None
    return found[0].execution_id if found else None


def _clamp_ms(value: int | None, default: int, low: int, high: int) -> float:
    ms = default if value is None else value
    return min(max(ms, low), high) / 1000.0


class DaemonHarnessSandbox[InstanceT: RunningInstance](HarnessSandbox):
    def __init__(
        self,
        *,
        archive_store: ArchiveStorage | None,
        turn_end_save_interval_seconds: int,
    ) -> None:
        # None: no session saves.
        self._archives = archive_store
        self._turn_end_save_interval = turn_end_save_interval_seconds
        self.turn_save = BackgroundTurnSave(self._save_after_turn)

    # Backend hooks

    @abc.abstractmethod
    def _instance(self, sandbox: HarnessSandboxKey) -> InstanceT:
        """The running, initialized instance; starts one if needed."""

    @abc.abstractmethod
    def _instance_if_running(
        self, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> InstanceT | None:
        """The instance when it runs, without starting one."""

    @abc.abstractmethod
    def _transfer(self, instance: InstanceT) -> SessionTransfer | None:
        """Session saves to and from `instance`; None without saves."""

    @abc.abstractmethod
    def _mark_session_set_up(
        self, tenant_cache: CacheBackend, ref: HarnessSandboxRef, instance: InstanceT
    ) -> None:
        """Record the session as set up on `instance`. Raises
        HarnessSandboxError when the instance stopped meanwhile (an idle stop
        saved and stopped it)."""

    @abc.abstractmethod
    def _stop(
        self, tenant_id: str, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> None:
        """Stop the sandbox for a purge and forget its instance."""

    @abc.abstractmethod
    def _forget_sandbox(self, tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
        """Delete the backend's own records of a purged sandbox."""

    # Lifecycle

    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        self._instance(ref)

    def install_skill(
        self,
        ref: HarnessSandboxRef,
        name: str,
        version: str,
        files: FileSet,
    ) -> bool:
        if posixpath.basename(name) != name or name.startswith("."):
            raise HarnessSandboxError(f"bad skill name {name!r}")
        if any(not path.startswith(f"{name}/") for path in files):
            raise HarnessSandboxError(f"skill {name!r} has files outside its folder")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path in sorted(files):
                data = files[path]
                info = tarfile.TarInfo(path)
                info.size = len(data)
                # FileSet keeps no modes: a script or a binary runs directly.
                info.mode = 0o755 if data.startswith((b"#!", b"\x7fELF")) else 0o644
                tar.addfile(info, io.BytesIO(data))
        daemon = self._instance(ref).daemon
        installed = daemon.install_skill(
            name=name, version=version, tar=buffer.getvalue()
        )
        logger.info(
            "Skill %s (version %s) %s sandbox %s",
            name,
            version,
            "copied into" if installed else "already in",
            ref.sandbox_id,
        )
        return installed

    # Activity

    def begin_turn(self, ref: HarnessSandboxRef) -> None:
        set_mark(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            f"turn:{ref.session_id}",
            TURN_LEASE_SECONDS,
        )
        self.touch(ref)

    def end_turn(self, ref: HarnessSandboxRef) -> None:
        set_mark(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            f"turn:{ref.session_id}",
            None,
        )
        self.touch(ref)
        if self._archives is not None and self._turn_end_save_interval:
            self.turn_save.submit(ref)

    def _save_after_turn(self, ref: HarnessSandboxRef) -> None:
        """Save the session on its running instance, unless a new turn
        began, its last save is recent, or another save of it runs. Never
        starts the sandbox and never blocks a call."""
        store = self._archives
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        if store is None or has_marks(
            tenant_cache, ref.sandbox_id, f"turn:{ref.session_id}"
        ):
            return
        last = get_session_save(tenant_cache, ref.session_id)
        if (
            last is not None
            and time.time() - last.saved_at < self._turn_end_save_interval
        ):
            return
        instance = self._instance_if_running(tenant_cache, ref.sandbox_id)
        if instance is None:
            return
        # Only a session restored on this instance: a save of a session that
        # was never set up here would replace its last save with less.
        if ref.session_id not in sessions_on_instance(
            tenant_cache, ref.sandbox_id, instance.identity
        ):
            return
        with session_save_lock(tenant_cache, ref.session_id) as held:
            if not held:
                return
            transfer = self._transfer(instance)
            if transfer is None:
                return
            with tenant_scope(ref.tenant_id):
                save_session(
                    tenant_cache,
                    instance.daemon,
                    transfer,
                    store,
                    ref.sandbox_id,
                    ref.session_id,
                )

    def set_approval_parked(self, ref: HarnessSandboxRef, parked: bool) -> None:
        set_mark(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            f"approval:{ref.session_id}",
            APPROVAL_PARK_SECONDS if parked else None,
        )

    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        if has_marks(tenant_cache, sandbox_id):
            return True
        try:
            instance = self._instance_if_running(tenant_cache, sandbox_id)
            if instance is None:
                return False
            health = instance.daemon.health()
        except (HostAgentError, SandboxDaemonError):
            # Unknown counts as busy: never stop a sandbox on a failed check.
            logger.warning(
                "sandbox_fc_busy_check_failed sandbox=%s", sandbox_id, exc_info=True
            )
            return True
        return health.running_executions > 0

    # Exec

    def _session_vm(
        self, ref: HarnessSandboxRef
    ) -> tuple[InstanceT, SandboxDaemonClient]:
        """The running instance and its daemon, with the session's last save
        restored once per instance. Uses no command slot."""
        instance = self._instance(ref)
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)

        def set_up() -> bool:
            return ref.session_id in sessions_on_instance(
                tenant_cache, ref.sandbox_id, instance.identity
            )

        if set_up():
            return instance, instance.daemon
        with tenant_cache.lock(
            f"{_SESSION_SETUP_LOCK_PREFIX}{ref.sandbox_id}:{ref.session_id}",
            timeout=_SESSION_SETUP_LOCK_SECONDS,
        ):
            if set_up():
                return instance, instance.daemon
            transfer = self._transfer(instance)
            if transfer is not None:
                try:
                    with tenant_scope(ref.tenant_id):
                        restore_session(tenant_cache, transfer, ref.session_id)
                except (HostAgentError, SandboxDaemonError) as e:
                    raise SessionSaveError(
                        f"could not restore the saved files of this session: {e}"
                    ) from e
            self._mark_session_set_up(tenant_cache, ref, instance)
        return instance, instance.daemon

    def exec_command(
        self,
        ref: HarnessSandboxRef,
        cmd: str,
        *,
        workdir: str | None = None,
        yield_time_ms: int | None = None,
    ) -> Generator[ExecEvent]:
        """Starts the command when the iterator is first read."""
        buffer = ExecOutputBuffer()
        yield_seconds = _clamp_ms(
            yield_time_ms,
            EXEC_DEFAULT_YIELD_MS,
            EXEC_MIN_YIELD_MS,
            EXEC_MAX_YIELD_MS,
        )
        instance, daemon = self._session_vm(ref)
        start_label = {_START_LABEL: secrets.token_hex(16)}
        # A Stop that came during the wake starts no command.
        if (cancellation := current_cancellation()) is not None:
            cancellation.check()
        try:
            # The daemon makes the session directory, the default cwd.
            execution_id = daemon.start(
                ExecCommand(
                    argv=["bash", "-c", cmd],
                    cwd=workdir or "",
                    # Each chat session drives its own browser in the shared
                    # sandbox.
                    env={"AGENT_BROWSER_SESSION": str(ref.session_id)},
                    stdin=True,
                    deadline_seconds=EXEC_DEADLINE_SECONDS,
                    labels=start_label,
                    session_id=str(ref.session_id),
                )
            ).execution_id
        except SandboxDaemonError as e:
            if e.reason in _EXEC_CAP_REASONS:
                raise ExecCapReachedError() from e
            raise
        except HostAgentError:
            # No answer: the command may run. Adopt it by its label.
            execution_id = _find_started(daemon, start_label)
            if execution_id is None:
                raise
        record = ExecSessionRecord(
            exec_session_id=secrets.token_hex(4),
            chat_session_id=str(ref.session_id),
            execution_id=execution_id,
            attempt=instance.attempt,
            generation=instance.generation,
            last_used=time.time(),
        )
        # The yield window counts from the start, not from the call: a wake
        # and the Start take time that the command did not get.
        until = time.monotonic() + yield_seconds
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        try:
            put_exec_session(tenant_cache, ref.sandbox_id, record)
        except Exception:
            # Without a record nobody can reach the command: stop it.
            daemon.cancel(record.execution_id)
            raise
        yield from self._collect(
            tenant_cache, ref, daemon, record, until=until, buffer=buffer
        )

    def write_stdin(
        self,
        ref: HarnessSandboxRef,
        exec_session_id: str,
        chars: str = "",
        *,
        yield_time_ms: int | None = None,
    ) -> Generator[ExecEvent]:
        """Writes when the iterator is first read."""
        buffer = ExecOutputBuffer()
        if chars:
            yield_seconds = _clamp_ms(
                yield_time_ms,
                WRITE_STDIN_DEFAULT_YIELD_MS,
                EXEC_MIN_YIELD_MS,
                WRITE_STDIN_MAX_YIELD_MS,
            )
        else:
            yield_seconds = _clamp_ms(
                yield_time_ms,
                POLL_MIN_YIELD_MS,
                POLL_MIN_YIELD_MS,
                POLL_MAX_YIELD_MS,
            )
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        record = get_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
        if record is None or record.chat_session_id != str(ref.session_id):
            raise ExecSessionNotFoundError(exec_session_id)
        instance = self._instance(ref)
        if (record.attempt, record.generation) != instance.identity:
            # Processes do not survive a restart.
            remove_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
            raise ExecSessionEndedError(exec_session_id)
        daemon = instance.daemon
        text, interrupt, _ = chars.partition(INTERRUPT_CHAR)
        # A Stop that came before the write writes nothing.
        if (cancellation := current_cancellation()) is not None:
            cancellation.check()
        try:
            if text:
                daemon.interact(record.execution_id, data=text.encode())
            if interrupt:
                daemon.cancel(record.execution_id, CancelSignal.SIGINT)
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND:
                remove_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
                raise ExecSessionEndedError(exec_session_id) from e
            # An ended command: report its result below.
            if e.reason is not SandboxDaemonErrorReason.EXECUTION_ENDED:
                raise
        yield from self._collect(
            tenant_cache,
            ref,
            daemon,
            record,
            # From the write, as for exec_command.
            until=time.monotonic() + yield_seconds,
            buffer=buffer,
        )

    def _collect(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        daemon: SandboxDaemonClient,
        record: ExecSessionRecord,
        *,
        until: float,
        buffer: ExecOutputBuffer,
    ) -> Generator[ExecEvent]:
        """Stream new output into `buffer` until the command ends or `until`
        passes, then yield the result and save the read offsets. A cancel of
        the current signal (a Stop, or the end of the calling code mode cell)
        ends the wait and kills the command, however the wait ends (also when
        the consumer drops this iterator), then raises AgentCancelled."""
        buffer.session_id = record.exec_session_id
        offsets = {
            OutputStream.STDOUT: record.stdout_offset,
            OutputStream.STDERR: record.stderr_offset,
        }
        result: ExecResult | None = None
        stream_error: SandboxDaemonError | HostAgentError | None = None
        cancellation = current_cancellation()
        stopped = False
        try:
            for event in daemon.stream(
                record.execution_id,
                stdout_offset=offsets[OutputStream.STDOUT],
                stderr_offset=offsets[OutputStream.STDERR],
                window_seconds=max(until - time.monotonic(), 0.001),
                on_cancel=None if cancellation is None else cancellation.on_cancel,
            ):
                text = ""
                if isinstance(event, ExecOutput):
                    skip = max(offsets[event.stream] - event.offset, 0)
                    offsets[event.stream] = max(
                        offsets[event.stream], event.offset + len(event.data)
                    )
                    text = buffer.add(event.stream, event.data[skip:])
                elif isinstance(event, ExecGap):
                    if event.end > offsets[event.stream]:
                        lost = event.end - max(offsets[event.stream], event.start)
                        offsets[event.stream] = event.end
                        text = buffer.add_gap(event.stream, lost)
                elif isinstance(event, ExecResult):
                    result = event
                if text:
                    yield ExecOutputDelta(text=text)
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND:
                remove_exec_session(
                    tenant_cache, ref.sandbox_id, record.exec_session_id
                )
                buffer.session_id = None
                raise ExecSessionEndedError(record.exec_session_id) from e
            stream_error = e
        except HostAgentError as e:
            stream_error = e
        finally:
            # Also when the stream failed meanwhile or the consumer stopped
            # reading.
            stopped = result is None and self._kill_if_stopped(
                tenant_cache, ref, daemon, record, buffer, cancellation
            )
        if stopped and cancellation is not None:
            cancellation.check()
        if isinstance(stream_error, HostAgentError):
            # The connection broke, not the command: it keeps running, and
            # its record (with the last saved offsets) stays.
            raise HarnessSandboxError(
                f"Lost the output stream of the command ({stream_error}). It "
                f"may still run: poll it with write_stdin and session ID "
                f"{record.exec_session_id}."
            ) from stream_error
        if stream_error is not None:
            raise stream_error
        if result is None:
            # The next call reads an incomplete character again.
            put_exec_session(
                tenant_cache,
                ref.sandbox_id,
                record.model_copy(
                    update={
                        "stdout_offset": offsets[OutputStream.STDOUT]
                        - buffer.pending_bytes(OutputStream.STDOUT),
                        "stderr_offset": offsets[OutputStream.STDERR]
                        - buffer.pending_bytes(OutputStream.STDERR),
                        "last_used": time.time(),
                    }
                ),
            )
        else:
            remove_exec_session(tenant_cache, ref.sandbox_id, record.exec_session_id)
            buffer.session_id = None
            if text := buffer.finish():
                yield ExecOutputDelta(text=text)
        exited = result is not None and result.completion is ExecCompletion.EXITED
        yield ExecCommandResult(
            head=buffer.head,
            tail=buffer.tail,
            omitted_chars=buffer.omitted_chars,
            session_id=buffer.session_id,
            exit_code=result.exit_code if result is not None and exited else None,
            completion=None
            if result is None
            else _COMPLETION_NAMES.get(result.completion),
            wall_time_seconds=time.monotonic() - buffer.started_at,
            truncated=buffer.truncated,
        )

    def _kill_if_stopped(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        daemon: SandboxDaemonClient,
        record: ExecSessionRecord,
        buffer: ExecOutputBuffer,
        cancellation: CancellationSignal | None,
    ) -> bool:
        """If the current signal stopped the call, kill its command and drop
        its record; returns whether it stopped. A failed kill keeps the
        record (and the buffer's session ID), so write_stdin can still reach
        the command."""
        if cancellation is None or not cancellation.cancelled:
            return False
        try:
            daemon.cancel(record.execution_id)
            remove_exec_session(tenant_cache, ref.sandbox_id, record.exec_session_id)
            buffer.session_id = None
        except Exception:
            logger.warning(
                "sandbox_fc_stop_kill_failed sandbox=%s execution=%s",
                ref.sandbox_id,
                record.execution_id,
                exc_info=True,
            )
        return True

    # Files (paths relative to the session directory, or under
    # ONYX_VM_FILES_ROOT)

    def _file_target(
        self, ref: HarnessSandboxRef, path: str
    ) -> tuple[SandboxDaemonClient, str, str]:
        """The daemon, session ID and path of a file call. A path under
        ONYX_VM_FILES_ROOT goes with no session ID: the daemon takes it
        absolute, and no session is restored. Any other path is
        session-relative ("" = the session directory), checked before the
        sandbox starts."""
        onyx_path = onyx_vm_path(path)
        if onyx_path is not None:
            return self._instance(ref).daemon, "", onyx_path
        rel = session_relative_path(ref.session_id, path)
        return self._session_vm(ref)[1], str(ref.session_id), rel

    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        try:
            daemon, session_id, target = self._file_target(ref, path)
        except SandboxPathError as e:
            raise SandboxPathError(
                f"{path!r} is not in the working directory or under "
                f"{ONYX_VM_FILES_ROOT}; copy the file into the working "
                "directory first"
            ) from e
        return _read(daemon, session_id, target, max_bytes=max_bytes, path=path)

    def write_file(
        self,
        ref: HarnessSandboxRef,
        path: str,
        data: bytes | IO[bytes] | list[bytes],
        *,
        mode: int = 0o644,
        timeout_seconds: float | None = None,
    ) -> None:
        if not mode & 0o7777:
            # The guest daemon reads mode 0 as "not set" and writes 0644.
            raise HarnessSandboxError(
                f"cannot write {path!r} with mode 000; change its mode with "
                "a shell command first"
            )
        daemon, session_id, target = self._file_target(ref, path)
        _write(daemon, session_id, target, data, mode, timeout_seconds, overwrite=True)
        tool_results = session_tool_results(ref.session_id)
        if target.startswith(tool_results + "/") and is_purged(
            get_cache_backend(tenant_id=ref.tenant_id), ref.sandbox_id, ref.session_id
        ):
            # The purge marks the session before it deletes the directory, so
            # a write that it missed sees the mark.
            daemon.delete_file(session_id="", path=tool_results, recursive=True)
            raise HarnessSandboxError(f"session {ref.session_id} was deleted")

    def delete_listed_files(
        self,
        ref: HarnessSandboxRef,
        directory: str,
        select: Callable[[FileListing], Iterable[str]],
        *,
        max_entries: int,
    ) -> None:
        daemon, session_id, target = self._file_target(ref, directory)
        try:
            listing = daemon.list_files(
                session_id=session_id,
                path=target,
                recursive=True,
                max_entries=max_entries,
            )
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.FILE_NOT_FOUND:
                return
            raise
        listed = {entry.path for entry in listing.entries}
        for path in select(listing):
            if path in listed:
                daemon.delete_file(session_id=session_id, path=path)

    def stat_files(
        self, ref: HarnessSandboxRef, paths: Sequence[str]
    ) -> list[SandboxPathInfo]:
        rels = [session_relative_path(ref.session_id, path) or "." for path in paths]
        _, daemon = self._session_vm(ref)
        # Batches within the daemon's caps of paths and path bytes.
        batches: list[list[str]] = [[]]
        size = 0
        for rel in rels:
            if len(batches[-1]) == STAT_FILES_MAX_PATHS or (
                batches[-1] and size + len(rel.encode()) > STAT_FILES_MAX_PATH_BYTES
            ):
                batches.append([])
                size = 0
            batches[-1].append(rel)
            size += len(rel.encode())
        stats: list[PathStat] = []
        try:
            for batch in batches:
                if batch:
                    stats += daemon.stat_files(
                        session_id=str(ref.session_id), paths=batch
                    )
        except (HostAgentError, SandboxDaemonError) as e:
            if e.code is grpc.StatusCode.UNIMPLEMENTED:
                raise HarnessSandboxError(
                    "This sandbox runs an older image without file checks; it "
                    "updates after the sandbox restarts."
                ) from e
            raise
        return [
            SandboxPathInfo(
                exists=found.exists,
                is_link=found.type is FileType.SYMLINK,
                link_target=found.link_target
                if found.type is FileType.SYMLINK
                else None,
                type=_SANDBOX_FILE_TYPES.get(found.target_type)
                if found.target_error is None
                else None,
                mode=found.target_mode if found.target_error is None else None,
                identity=(found.device, found.inode)
                if found.target_error is None
                else None,
                error=_STAT_ERRORS.get(found.target_error)
                if found.target_error is not None
                else None,
            )
            for found in stats
        ]

    def delete_file(self, ref: HarnessSandboxRef, path: str) -> bool:
        return _delete(*self._file_target(ref, path))

    def session_files(self, ref: HarnessSandboxRef) -> SessionFiles:
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        if is_purged(tenant_cache, ref.sandbox_id, ref.session_id):
            raise HarnessSandboxError("This chat session was deleted.")
        _, daemon = self._session_vm(ref)
        return _SessionFiles(daemon, tenant_cache, ref)

    # Renders

    def render_preview(
        self,
        source: RenderSessionFile | RenderFileBytes,
        *,
        first_page: bool,
        budget_seconds: float,
    ) -> RenderedPreview | None:
        if isinstance(source, RenderSessionFile):
            sandbox: HarnessSandboxKey = source.ref
            name = source.path
        else:
            sandbox = source.sandbox
            name = f"source{source.suffix}"
        suffix = posixpath.splitext(name)[1].lower()
        if suffix not in RENDER_PREVIEW_SUFFIXES:
            return None
        scratch = f"{RENDER_PREVIEW_ROOT}/{secrets.token_hex(16)}"
        log_context = f"sandbox={sandbox.sandbox_id} path={name!r}"
        daemon: SandboxDaemonClient | None = None
        try:
            if isinstance(source, RenderSessionFile):
                daemon, session_id, target = self._file_target(source.ref, source.path)
                until = time.monotonic() + budget_seconds
                rendered = (
                    posixpath.join(session_workspace(source.ref.session_id), target)
                    if session_id
                    else target
                )
                if not _run_render_step(
                    daemon,
                    ["mkdir", "-p", scratch],
                    {},
                    session_id=session_id,
                    until=until,
                    log_context=log_context,
                ):
                    return None
            else:
                daemon = self._instance(sandbox).daemon
                session_id = ""
                until = time.monotonic() + budget_seconds
                rendered = f"{scratch}/{name}"
                # Creates the scratch directory.
                with _render_transfer(until, "the source write") as remaining:
                    _write(
                        daemon,
                        "",
                        rendered,
                        source.data,
                        0o644,
                        remaining,
                        overwrite=True,
                    )
            converted: str | None = None
            pdf: bytes | None = None
            if suffix != ".pdf":
                if not _run_render_step(
                    daemon,
                    [
                        "soffice",
                        # A profile of its own, so renders run side by side.
                        f"-env:UserInstallation=file://{scratch}/profile",
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        scratch,
                        rendered,
                    ],
                    {"SAL_USE_VCLPLUGIN": "svp"},
                    session_id=session_id,
                    until=until,
                    log_context=log_context,
                ):
                    return None
                # LibreOffice names the PDF after the source, without its
                # suffix.
                stem = posixpath.splitext(posixpath.basename(rendered))[0]
                converted = f"{scratch}/{stem}.pdf"
                try:
                    with _render_transfer(until, "the PDF read") as remaining:
                        pdf = _read(
                            daemon,
                            "",
                            converted,
                            max_bytes=RENDER_PREVIEW_MAX_PDF_BYTES,
                            path=converted,
                            timeout_seconds=remaining,
                        )
                except SandboxFileNotFoundError:
                    # LibreOffice exits 0 when it cannot load the source.
                    logger.warning(
                        "sandbox_fc_render_rejected %s: LibreOffice made no PDF",
                        log_context,
                    )
                    return None
                except SandboxFileTooLargeError:
                    logger.warning("sandbox_fc_render_pdf_too_large %s", log_context)
            page: bytes | None = None
            if first_page and _run_render_step(
                daemon,
                [
                    "pdftoppm",
                    "-jpeg",
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-scale-to",
                    str(RENDER_PREVIEW_SIZE_PX),
                    "-singlefile",
                    converted or rendered,
                    f"{scratch}/page",
                ],
                {},
                session_id=session_id,
                until=until,
                log_context=log_context,
            ):
                try:
                    with _render_transfer(until, "the first page read") as remaining:
                        page = _read(
                            daemon,
                            "",
                            f"{scratch}/page.jpg",
                            max_bytes=RENDER_PREVIEW_MAX_OUTPUT_BYTES,
                            path=f"{scratch}/page.jpg",
                            timeout_seconds=remaining,
                        )
                except (SandboxFileNotFoundError, SandboxFileTooLargeError):
                    logger.warning(
                        "sandbox_fc_render_no_first_page %s", log_context, exc_info=True
                    )
            # A PDF source has no output but its first page.
            if converted is None and page is None:
                return None
            return RenderedPreview(first_page=page, pdf=pdf)
        except Exception:
            # A failure after a Stop is the Stop.
            check_cancelled()
            raise
        finally:
            if daemon is not None:
                try:
                    daemon.delete_file(session_id="", path=scratch, recursive=True)
                except Exception:
                    logger.warning(
                        "sandbox_fc_render_cleanup_failed %s dir=%s",
                        log_context,
                        scratch,
                        exc_info=True,
                    )

    # Purge (delete hooks). Each step runs even when an earlier one failed;
    # the call raises at the end if any step failed.

    def purge_session(
        self,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        session_id: UUID,
        retention: bool = False,
    ) -> None:
        """Delete a chat session's save, its working directory on the running
        VM, its tool results (the purge rule at TOOL_RESULTS_ROOT) and its exec
        records. A session that never used the sandbox costs a few cache reads
        and, while the VM runs, one delete. `retention`: see `mark_purged`."""
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        mark_purged(tenant_cache, session_id=session_id, retention=retention)
        errors: list[Exception] = []
        try:
            # Copies of the chat stop before its directory goes.
            tenant_cache.incr(copy_generation_key(session_id), ex=COPY_STATE_SECONDS)
        except Exception as e:
            errors.append(e)
        instance: InstanceT | None = None
        try:
            instance = self._instance_if_running(tenant_cache, sandbox_id)
        except Exception as e:
            errors.append(e)
        try:
            # Before the directory deletes: a command can write them again.
            self._drop_session_commands(tenant_cache, instance, sandbox_id, session_id)
        except Exception as e:
            errors.append(e)
        # The purge rule at TOOL_RESULTS_ROOT: no record shows a spill.
        # VM-wide paths: a session-relative call cannot delete a session
        # directory itself.
        try:
            if instance is not None:
                instance.daemon.delete_file(
                    session_id="", path=session_tool_results(session_id), recursive=True
                )
        except Exception as e:
            # The directory goes with the VM at its next stop.
            errors.append(e)
        # A session gets a working directory only on a VM instance that
        # records it; its save has records too. A failed lookup counts as
        # records, so every step runs.
        try:
            recorded = has_session_records(tenant_cache, sandbox_id, session_id)
        except Exception as e:
            errors.append(e)
            recorded = True
        if not recorded:
            _raise_first(errors, f"session {session_id}")
            return
        try:
            if instance is not None:
                instance.daemon.delete_file(
                    session_id="", path=session_workspace(session_id), recursive=True
                )
        except Exception as e:
            errors.append(e)
        try:
            forget_session_on_instances(tenant_cache, sandbox_id, session_id)
        except Exception as e:
            errors.append(e)
        try:
            with tenant_scope(tenant_id):
                delete_session_archives(
                    tenant_cache, self._archives, sandbox_id, session_id
                )
        except Exception as e:
            errors.append(e)
        _raise_first(errors, f"session {session_id}")
        logger.info(
            "sandbox_fc_session_purged sandbox=%s session=%s", sandbox_id, session_id
        )

    def _drop_session_commands(
        self,
        tenant_cache: CacheBackend,
        instance: InstanceT | None,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> None:
        """Remove the session's exec records; cancel its commands on the
        running instance, if any."""
        table = ExecSessionTable.model_validate_json(
            tenant_cache.get(EXEC_SESSIONS_PREFIX + str(sandbox_id)) or b"{}"
        )
        for record in table.sessions.values():
            if record.chat_session_id != str(session_id):
                continue
            if (
                instance is not None
                and (
                    record.attempt,
                    record.generation,
                )
                == instance.identity
            ):
                try:
                    instance.daemon.cancel(record.execution_id)
                except (HostAgentError, SandboxDaemonError):
                    # The command stops with the sandbox at the latest.
                    pass
            remove_exec_session(tenant_cache, sandbox_id, record.exec_session_id)

    def purge_sandbox(
        self,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        session_ids: list[UUID] | None = None,
    ) -> None:
        """Stop the sandbox (its disk goes with it) and delete every save and
        record of the sandbox. `session_ids` adds sessions that the
        saved-session index may not name."""
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        mark_purged(tenant_cache, sandbox_id=sandbox_id)
        # A stop that saves the sandbox now gives way to the purge.
        note_wanted(tenant_cache, sandbox_id)
        errors: list[Exception] = []
        try:
            self._stop(tenant_id, tenant_cache, sandbox_id)
        except Exception as e:
            # With no record left, the backend stops the sandbox as an orphan.
            errors.append(e)
        instances = SessionInstanceTable.model_validate_json(
            tenant_cache.get(SESSION_INSTANCES_PREFIX + str(sandbox_id)) or b"{}"
        )
        sessions = set(get_ids(tenant_cache, SAVED_SESSIONS_PREFIX, sandbox_id))
        sessions |= {str(s) for s in session_ids or []}
        with tenant_scope(tenant_id):
            for session_id in sorted(sessions | set(instances.sessions)):
                try:
                    delete_session_archives(
                        tenant_cache, self._archives, sandbox_id, UUID(session_id)
                    )
                except Exception as e:
                    errors.append(e)
        self._forget_sandbox(tenant_cache, sandbox_id)
        # The saved-session index keeps what failed, for a retry.
        for prefix in SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))
        _raise_first(errors, f"sandbox {sandbox_id}")
        logger.info("sandbox_fc_sandbox_purged sandbox=%s", sandbox_id)


def _raise_first(errors: list[Exception], what: str) -> None:
    if errors:
        for e in errors[1:]:
            logger.warning("sandbox_fc_purge_step_failed %s: %s", what, e)
        raise errors[0]


@contextmanager
def _render_transfer(until: float, what: str) -> Iterator[float]:
    """The seconds left of a render's budget, which ends at `until`
    (time.monotonic()), for one file transfer, `what`. Raises
    RenderBudgetSpentError when none is left, or when the transfer runs past
    them (a gRPC DEADLINE_EXCEEDED); other errors pass through."""
    remaining = until - time.monotonic()
    if remaining <= 0:
        raise RenderBudgetSpentError(f"the render budget ran out before {what}")
    try:
        yield remaining
    except (HostAgentError, SandboxDaemonError) as e:
        if e.code is grpc.StatusCode.DEADLINE_EXCEEDED:
            raise RenderBudgetSpentError(f"{what} ran past the render budget") from e
        raise


def _run_render_step(
    daemon: SandboxDaemonClient,
    argv: list[str],
    env: dict[str, str],
    *,
    session_id: str,
    until: float,
    log_context: str,
) -> bool:
    """Run one render step by `until` (time.monotonic()). True when it exits
    0; False, logged, when the program fails. Raises RenderBudgetSpentError
    when no time is left or the step runs past it. A cancel of the current
    signal, or a stream that breaks, kills the step."""
    check_cancelled()
    remaining = until - time.monotonic()
    if remaining <= 0:
        raise RenderBudgetSpentError(f"the render budget ran out before {argv[0]}")
    cancellation = current_cancellation()
    # The execution ID of the step, once it started.
    running: list[str] = []

    def kill() -> None:
        if running:
            daemon.cancel(running[0])

    result: ExecResult | None = None
    output = b""
    try:
        with nullcontext() if cancellation is None else cancellation.on_cancel(kill):
            for event in daemon.run(
                ExecCommand(
                    argv=argv,
                    env=env,
                    deadline_seconds=remaining,
                    session_id=session_id,
                )
            ):
                if isinstance(event, ExecStarted):
                    running.append(event.execution_id)
                    # A cancel before the start found nothing to kill: the
                    # clean-up below kills it.
                    if cancellation is not None and cancellation.cancelled:
                        break
                elif isinstance(event, ExecOutput):
                    output = (output + event.data)[-_RENDER_LOG_OUTPUT_BYTES:]
                elif isinstance(event, ExecResult):
                    result = event
    finally:
        # A step without a result may still run: kill it, so it writes
        # nothing in the scratch directory after its delete.
        if result is None:
            try:
                kill()
            except Exception:
                logger.warning(
                    "sandbox_fc_render_kill_failed %s execution=%s",
                    log_context,
                    running,
                    exc_info=True,
                )
    check_cancelled()
    if result is None:
        # The run stream raises when it ends without a result, so only a
        # Stop, which raised above, leaves none.
        raise RuntimeError(f"Bug: {argv[0]} ended without a result")
    if result.completion is ExecCompletion.DEADLINE_EXCEEDED:
        raise RenderBudgetSpentError(f"{argv[0]} ran past the render budget")
    if result.completion is ExecCompletion.EXITED and result.exit_code == 0:
        return True
    logger.warning(
        "sandbox_fc_render_rejected %s step=%s: %s with exit code %s: %s",
        log_context,
        argv[0],
        result.completion.value,
        result.exit_code,
        output.decode(errors="replace").strip(),
    )
    return False


def _write(
    daemon: SandboxDaemonClient,
    session_id: str,
    target: str,
    data: bytes | IO[bytes] | list[bytes],
    mode: int,
    timeout_seconds: float | None,
    *,
    overwrite: bool,
) -> None:
    """The write of write_file and SessionFiles.write."""
    if not target:
        raise SandboxPathError("cannot write the session directory itself")
    daemon.write_file(
        session_id=session_id,
        path=target,
        data=data,
        mode=mode,
        overwrite=overwrite,
        timeout_seconds=timeout_seconds,
    )


def _read(
    daemon: SandboxDaemonClient,
    session_id: str,
    target: str,
    *,
    max_bytes: int,
    path: str,
    timeout_seconds: float | None = None,
) -> bytes:
    """The read of read_file and the render. `path` names the file in
    errors. `timeout_seconds` replaces the transfer timeout."""
    # Dropping the chunk iterator unread cancels the stream.
    try:
        info, chunks = daemon.read_file(
            session_id=session_id,
            path=target,
            length=max_bytes + 1,
            timeout_seconds=timeout_seconds,
        )
    except SandboxDaemonError as e:
        if e.reason is SandboxDaemonErrorReason.FILE_NOT_FOUND:
            raise SandboxFileNotFoundError(path) from e
        if e.reason is SandboxDaemonErrorReason.INVALID_ARGUMENT:
            # Not a regular file, a link out of its root, or a denied
            # path; the daemon's message names the path.
            raise HarnessSandboxError(e.message) from e
        raise
    data = b"" if info.size > max_bytes else b"".join(chunks)
    if info.size > max_bytes or len(data) > max_bytes:
        raise SandboxFileTooLargeError(
            f"{path!r} is larger than the limit of {max_bytes} bytes"
        )
    return data


def _delete(daemon: SandboxDaemonClient, session_id: str, target: str) -> bool:
    """The delete of delete_file and SessionFiles.delete."""
    if not target:
        raise SandboxPathError("cannot delete the session directory itself")
    return daemon.delete_file(session_id=session_id, path=target)


class _SessionFiles(SessionFiles):
    def __init__(
        self,
        daemon: SandboxDaemonClient,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
    ) -> None:
        self._daemon = daemon
        self._cache = tenant_cache
        self._ref = ref
        self._mark = f"copy:{uuid4().hex}"

    def write(
        self, path: str, data: IO[bytes], *, timeout_seconds: float, overwrite: bool
    ) -> None:
        session_id = self._ref.session_id
        _write(
            self._daemon,
            str(session_id),
            session_relative_path(self._ref.session_id, path),
            data,
            0o644,
            timeout_seconds,
            overwrite=overwrite,
        )
        if is_purged(self._cache, self._ref.sandbox_id, session_id):
            # The purge marks the session before it deletes the directory, so
            # a write that it missed sees the mark.
            self._daemon.delete_file(
                session_id="", path=session_workspace(session_id), recursive=True
            )
            raise HarnessSandboxError(f"session {session_id} was deleted")

    def delete(self, path: str) -> bool:
        # The daemon opens the session directory without creating it.
        return _delete(
            self._daemon,
            str(self._ref.session_id),
            session_relative_path(self._ref.session_id, path),
        )

    def list_files(
        self, directory: str, *, max_entries: int, include_hidden: bool = False
    ) -> FileListing:
        try:
            return self._daemon.list_files(
                session_id=str(self._ref.session_id),
                path=session_relative_path(self._ref.session_id, directory),
                skip_hidden=not include_hidden,
                max_entries=max_entries,
            )
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.FILE_NOT_FOUND:
                return FileListing(entries=[], truncated=False)
            raise

    def mark_busy(self, seconds: float | None) -> None:
        set_mark(self._cache, self._ref.sandbox_id, self._mark, seconds)
