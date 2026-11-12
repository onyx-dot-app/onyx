"""Firecracker implementation of `HarnessSandbox` (`SANDBOX_RUNTIME=firecracker`).

One VM per user sandbox, placed on a host agent node. Each call wakes the VM
if needed (placement + wake in `onyx.microvm`) and runs the guest daemon Init
only when the daemon is not initialized. A session's first use on a VM
instance restores its last save (`session_saves`). Exec sessions live in
durable cache records (`harness_state`), so any API pod can serve
`write_stdin`.
"""

import mimetypes
import posixpath
import random
import secrets
import time
from collections.abc import Iterator
from io import BytesIO
from uuid import UUID

import grpc

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import FileOrigin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.microvm.agent_client import (
    HostAgentClientFactory,
    HostAgentError,
    MtlsHostAgentClientFactory,
)
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    SandboxVmUnusableError,
    UnknownActivity,
    VmStopOutcome,
    evict_idle_sandbox_vm,
    initialize_sandbox_vm,
    sandbox_daemon,
    wake_sandbox_vm,
)
from onyx.microvm.models import (
    CancelSignal,
    ExecCommand,
    ExecCompletion,
    ExecGap,
    ExecOutput,
    ExecResult,
    OutputStream,
    PlacedVm,
    VmInstance,
    VmRequest,
)
from onyx.microvm.placement import find_vm, sandbox_placement_lock
from onyx.microvm.registry import (
    get_registered_node,
    get_sandbox_daemon_key,
    get_sandbox_placement,
    touch_sandbox_placement,
)
from onyx.server.features.build.sandbox.exec_output import (
    ExecOutputBuffer,
    cut_to_tokens,
    estimate_tokens,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    get_exec_session,
    has_marks,
    last_attempt,
    mark_session_on_instance,
    put_exec_session,
    record_attempt,
    remove_exec_session,
    sessions_on_instance,
    set_mark,
)
from onyx.server.features.build.sandbox.firecracker.models import ExecSessionRecord
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    BackgroundIdleStop,
    SessionArchiveStore,
    SessionSaveCheckpointer,
    SessionSaveError,
    restore_session,
    tenant_scope,
)
from onyx.server.features.build.sandbox.harness_base import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    EXEC_DEFAULT_ENV,
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    INTERRUPT_CHAR,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
    ExecCapReachedError,
    ExecSessionEndedError,
    ExecSessionNotFoundError,
    HarnessSandbox,
    HarnessSandboxError,
    SandboxFileTooLargeError,
    SandboxPathError,
    session_workspace,
)
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecEvent,
    ExecOutputDelta,
    HarnessSandboxRef,
    SandboxProvisionContentionError,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# Deadline of one command. Background servers need a long one; the guest
# daemon caps it at 24 h.
EXEC_DEADLINE_SECONDS = 4 * 3600.0
# A wake retries a full node (a node takes a few Creates at a time) or a
# concurrent placement for this long, with backoff and jitter.
WAKE_RETRY_SECONDS = 10.0
# A turn mark expires after this long without a renewal (begin_turn).
TURN_LEASE_SECONDS = 15 * 60.0
# A parked approval keeps the sandbox busy for at most this long.
APPROVAL_PARK_SECONDS = 24 * 3600.0
# Largest session file that publish_artifact copies to the file store.
PUBLISH_MAX_BYTES = 100 << 20
# One Init per VM instance across API pods: a second Init resets egress
# connections that a command of the first may already use.
_INIT_LOCK_PREFIX = "sandbox_fc_harness_init:"
_INIT_LOCK_SECONDS = 30.0
# A session's restore runs once per VM instance across API pods; it
# covers a restore at the agent's 15 min transfer deadline.
_SESSION_SETUP_LOCK_PREFIX = "sandbox_fc:session_setup:"
_SESSION_SETUP_LOCK_SECONDS = 30 * 60.0
# Client token on each started command, to find it when Start gets no answer.
_START_LABEL = "onyx_start_id"


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


def session_relative_path(ref: HarnessSandboxRef, path: str) -> str:
    """The session-relative form of `path` ("" = the session directory).
    Accepts a relative path or an absolute path in the session directory."""
    root = session_workspace(ref.session_id)
    normalized = posixpath.normpath(path or ".")
    if posixpath.isabs(normalized):
        if normalized == root:
            return ""
        if not normalized.startswith(root + "/"):
            raise SandboxPathError(
                f"{path!r} is outside the session directory {root}; use "
                "exec_command elsewhere"
            )
        return normalized[len(root) + 1 :]
    if normalized == ".." or normalized.startswith("../"):
        raise SandboxPathError(f"{path!r} leaves the session directory")
    return "" if normalized == "." else normalized


class FirecrackerHarnessSandbox(HarnessSandbox, SandboxActivityProbe):
    def __init__(
        self,
        *,
        template: str,
        client_factory: HostAgentClientFactory | None = None,
        archive_store: SessionArchiveStore | None = None,
    ) -> None:
        if not template:
            raise ValueError("FirecrackerHarnessSandbox needs a template image tag")
        self._template = template
        self._client_factory = client_factory or MtlsHostAgentClientFactory()
        # None: no session saves, so the idle evictor keeps every VM.
        self._archive_store = archive_store
        self.idle_stop = BackgroundIdleStop(self._stop_if_idle)

    # Lifecycle

    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        self._place(ref)

    def _place(self, ref: HarnessSandboxRef) -> PlacedVm:
        """The running, initialized VM. Init runs only when the daemon is not
        initialized: a new boot, a VM adopted from a reservation, or a VM that
        placement replaced after a crash."""
        shared_cache = get_shared_cache_backend()
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        request = VmRequest(
            tenant_id=ref.tenant_id,
            sandbox_id=ref.sandbox_id,
            attempt=ref.attempt,
            template=self._template,
        )
        give_up_at = time.monotonic() + WAKE_RETRY_SECONDS
        delay = 0.25
        pause = 0.0
        last_error: Exception | None = None
        # The first attempt always runs.
        while last_error is None or time.monotonic() + pause < give_up_at:
            if last_error is not None:
                logger.info(
                    "sandbox_fc_wake_retry sandbox=%s pause=%.2f error=%s",
                    ref.sandbox_id,
                    pause,
                    last_error,
                )
                time.sleep(pause)
                delay = min(delay * 2, 2.0)
            # A stop deletes the placement record, and an agent never creates
            # a stopped attempt again: start past the last one.
            if get_sandbox_placement(tenant_cache, ref.sandbox_id) is None:
                floor = last_attempt(tenant_cache, ref.sandbox_id) + 1
                if request.attempt < floor:
                    request = request.model_copy(update={"attempt": floor})
            try:
                placed = wake_sandbox_vm(
                    shared_cache, tenant_cache, self._client_factory, request
                )
                if not self._initialized(placed):
                    self._initialize(tenant_cache, ref, placed)
                record_attempt(tenant_cache, ref.sandbox_id, placed.vm.attempt)
                return placed
            except (
                OnyxError,
                SandboxProvisionContentionError,
                SandboxVmUnusableError,
            ) as e:
                if isinstance(e, SandboxVmUnusableError):
                    # That VM is stopped: wake the next attempt.
                    request = request.model_copy(update={"attempt": e.attempt})
                elif (
                    isinstance(e, OnyxError)
                    and e.error_code is not OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
                ):
                    raise
                last_error = e
                pause = random.uniform(delay / 2, delay)
        raise last_error

    def _initialized(self, placed: PlacedVm) -> bool:
        health = sandbox_daemon(self._client_factory, placed).health()
        return health.initialized and health.generation == placed.vm.generation

    def _initialize(
        self, tenant_cache: CacheBackend, ref: HarnessSandboxRef, placed: PlacedVm
    ) -> None:
        """Init under a lock per VM instance; a waiter checks Health again."""
        vm = placed.vm
        lock = tenant_cache.lock(
            f"{_INIT_LOCK_PREFIX}{vm.sandbox_id}:{vm.attempt}:{vm.generation}",
            timeout=_INIT_LOCK_SECONDS,
        )
        if not lock.acquire(blocking_timeout=_INIT_LOCK_SECONDS):
            raise SandboxProvisionContentionError(
                f"sandbox {vm.sandbox_id} is initializing on another API pod"
            )
        try:
            if self._initialized(placed):
                return
            initialize_sandbox_vm(
                get_shared_cache_backend(),
                tenant_cache,
                self._client_factory,
                placed,
                tenant_id=ref.tenant_id,
                # No secrets: the egress proxy injects them.
                env=dict(EXEC_DEFAULT_ENV),
                session_ids=[],
            )
        finally:
            if lock.owned():
                lock.release()

    def _placed_if_running(
        self, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> PlacedVm | None:
        """The placed VM when it runs, without starting one."""
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None:
            return None
        node = get_registered_node(get_shared_cache_backend(), placement.node_id)
        if node is None:
            return None
        vms = self._client_factory.client(node.address).list_vms()
        vm = find_vm(vms, sandbox_id, placement.generation)
        if vm is None or vm.attempt != placement.attempt or not vm.state.is_live():
            return None
        key = get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt)
        if key is None:
            return None
        return PlacedVm(node=node, vm=vm, created=False, sandboxd_key=key)

    # Activity

    def touch(self, ref: HarnessSandboxRef) -> None:
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
        if placement is None:
            return
        touch_sandbox_placement(
            tenant_cache,
            ref.sandbox_id,
            node_id=placement.node_id,
            attempt=placement.attempt,
            generation=placement.generation,
            now=int(time.time()),
        )

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
            placed = self._placed_if_running(tenant_cache, sandbox_id)
            if placed is None:
                return False
            health = sandbox_daemon(self._client_factory, placed).health()
        except (HostAgentError, SandboxDaemonError):
            # Unknown counts as busy: never stop a VM on a failed check.
            logger.warning(
                "sandbox_fc_busy_check_failed sandbox=%s", sandbox_id, exc_info=True
            )
            return True
        return health.running_executions > 0

    # Exec

    def _session_vm(
        self, ref: HarnessSandboxRef
    ) -> tuple[PlacedVm, SandboxDaemonClient]:
        """The running VM and its daemon, with the session directory made
        and its last save restored, once per VM instance."""
        placed = self._place(ref)
        daemon = sandbox_daemon(self._client_factory, placed)
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        instance = (placed.vm.attempt, placed.vm.generation)

        def set_up() -> bool:
            return ref.session_id in sessions_on_instance(
                tenant_cache, ref.sandbox_id, instance
            )

        if set_up():
            return placed, daemon
        with tenant_cache.lock(
            f"{_SESSION_SETUP_LOCK_PREFIX}{ref.sandbox_id}:{ref.session_id}",
            timeout=_SESSION_SETUP_LOCK_SECONDS,
        ):
            if set_up():
                return placed, daemon
            # A command with the session makes its directory, so an idle
            # stop can list it even when no call wrote a file.
            made = list(
                daemon.run(ExecCommand(argv=["true"], session_id=str(ref.session_id)))
            )
            if not isinstance(made[-1], ExecResult) or made[-1].exit_code != 0:
                raise HarnessSandboxError(
                    f"could not create {session_workspace(ref.session_id)}"
                )
            if self._archive_store is not None:
                try:
                    with tenant_scope(ref.tenant_id):
                        restore_session(
                            tenant_cache,
                            self._client_factory.client(placed.node.address),
                            self._archive_store,
                            VmInstance(
                                sandbox_id=placed.vm.sandbox_id,
                                attempt=placed.vm.attempt,
                                generation=placed.vm.generation,
                                sandboxd_key=placed.sandboxd_key,
                            ),
                            ref.session_id,
                        )
                except (HostAgentError, SandboxDaemonError) as e:
                    raise SessionSaveError(
                        f"could not restore the saved files of this session: {e}"
                    ) from e
            # An idle stop that ran meanwhile has saved and stopped this
            # instance: do not record the session on it.
            with sandbox_placement_lock(tenant_cache, ref.sandbox_id, blocking=True):
                placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
                if (
                    placement is None
                    or (
                        placement.attempt,
                        placement.generation,
                    )
                    != instance
                ):
                    raise HarnessSandboxError(
                        "The sandbox stopped while this session was set up. "
                        "Run the call again."
                    )
                mark_session_on_instance(
                    tenant_cache, ref.sandbox_id, ref.session_id, instance
                )
        return placed, daemon

    # Idle stop

    def eviction_policy(self) -> tuple[SandboxCheckpointer, SandboxActivityProbe]:
        """The node-report idle evictor's save and busy checks."""
        if self._archive_store is None:
            return NoCheckpointSupport(), UnknownActivity()
        return self.idle_stop, self

    def session_checkpointer(self) -> SessionSaveCheckpointer | None:
        if self._archive_store is None:
            return None
        return SessionSaveCheckpointer(self._archive_store, self._client_factory, self)

    def _stop_if_idle(self, tenant_id: str, sandbox_id: UUID) -> VmStopOutcome:
        """Save every session, then stop the VM, while it is still idle and
        not busy (a queued stop can run late)."""
        checkpointer = self.session_checkpointer()
        if checkpointer is None:
            return VmStopOutcome.KEPT_NO_CHECKPOINT
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None:
            return VmStopOutcome.NOT_PLACED
        return evict_idle_sandbox_vm(
            get_shared_cache_backend(),
            tenant_cache,
            self._client_factory,
            checkpointer,
            self,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            last_active=placement.last_active,
            now=int(time.time()),
        )

    def exec_command(
        self,
        ref: HarnessSandboxRef,
        cmd: str,
        *,
        workdir: str | None = None,
        yield_time_ms: int | None = None,
        max_output_tokens: int | None = None,
    ) -> Iterator[ExecEvent]:
        """Starts the command when the iterator is first read."""
        started_at = time.monotonic()
        yield_seconds = _clamp_ms(
            yield_time_ms, EXEC_DEFAULT_YIELD_MS, EXEC_MIN_YIELD_MS, EXEC_MAX_YIELD_MS
        )
        placed, daemon = self._session_vm(ref)
        start_label = {_START_LABEL: secrets.token_hex(16)}
        try:
            # The daemon makes the session directory, the default cwd.
            execution_id = daemon.start(
                ExecCommand(
                    argv=["bash", "-c", cmd],
                    cwd=workdir or "",
                    stdin=True,
                    deadline_seconds=EXEC_DEADLINE_SECONDS,
                    labels=start_label,
                    session_id=str(ref.session_id),
                )
            ).execution_id
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_CAP_REACHED:
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
            attempt=placed.vm.attempt,
            generation=placed.vm.generation,
            last_used=time.time(),
        )
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        try:
            put_exec_session(tenant_cache, ref.sandbox_id, record)
        except Exception:
            # Without a record nobody can reach the command: stop it.
            daemon.cancel(record.execution_id)
            raise
        yield from self._collect(
            tenant_cache,
            ref,
            daemon,
            record,
            until=started_at + yield_seconds,
            started_at=started_at,
            max_output_tokens=max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def write_stdin(
        self,
        ref: HarnessSandboxRef,
        exec_session_id: str,
        chars: str = "",
        *,
        yield_time_ms: int | None = None,
        max_output_tokens: int | None = None,
    ) -> Iterator[ExecEvent]:
        """Writes when the iterator is first read."""
        started_at = time.monotonic()
        if chars:
            yield_seconds = _clamp_ms(
                yield_time_ms,
                WRITE_STDIN_DEFAULT_YIELD_MS,
                EXEC_MIN_YIELD_MS,
                WRITE_STDIN_MAX_YIELD_MS,
            )
        else:
            yield_seconds = _clamp_ms(
                yield_time_ms, POLL_MIN_YIELD_MS, POLL_MIN_YIELD_MS, POLL_MAX_YIELD_MS
            )
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        record = get_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
        if record is None or record.chat_session_id != str(ref.session_id):
            raise ExecSessionNotFoundError(exec_session_id)
        placed = self._place(ref)
        if (record.attempt, record.generation) != (
            placed.vm.attempt,
            placed.vm.generation,
        ):
            # Processes do not survive a VM restart.
            remove_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
            raise ExecSessionEndedError(exec_session_id)
        daemon = sandbox_daemon(self._client_factory, placed)
        text, interrupt, _ = chars.partition(INTERRUPT_CHAR)
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
            until=started_at + yield_seconds,
            started_at=started_at,
            max_output_tokens=max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def _collect(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        daemon: SandboxDaemonClient,
        record: ExecSessionRecord,
        *,
        until: float,
        started_at: float,
        max_output_tokens: int,
    ) -> Iterator[ExecEvent]:
        """Stream new output until the command ends or `until` passes, then
        yield the result and save the read offsets."""
        buffer = ExecOutputBuffer()
        offsets = {
            OutputStream.STDOUT: record.stdout_offset,
            OutputStream.STDERR: record.stderr_offset,
        }
        result: ExecResult | None = None
        try:
            for event in daemon.stream(
                record.execution_id,
                stdout_offset=offsets[OutputStream.STDOUT],
                stderr_offset=offsets[OutputStream.STDERR],
                timeout_seconds=max(until - time.monotonic(), 0.001),
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
        except HostAgentError as e:
            # The yield time passed while the command runs.
            if e.reached_agent or e.code is not grpc.StatusCode.DEADLINE_EXCEEDED:
                raise
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND:
                remove_exec_session(
                    tenant_cache, ref.sandbox_id, record.exec_session_id
                )
                raise ExecSessionEndedError(record.exec_session_id) from e
            raise
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
            if text := buffer.finish():
                yield ExecOutputDelta(text=text)
        full = buffer.text()
        output, cut = cut_to_tokens(full, max_output_tokens)
        exited = result is not None and result.completion is ExecCompletion.EXITED
        yield ExecCommandResult(
            output=output,
            exec_session_id=None if result is not None else record.exec_session_id,
            exit_code=result.exit_code if result is not None and exited else None,
            completion=result.completion.value.lower() if result is not None else None,
            wall_time_seconds=time.monotonic() - started_at,
            original_token_count=estimate_tokens(full),
            truncated=cut or buffer.truncated,
        )

    # Files (paths relative to the session directory)

    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        rel = session_relative_path(ref, path)
        _, daemon = self._session_vm(ref)
        # Dropping the chunk iterator unread cancels the stream.
        info, chunks = daemon.read_file(
            session_id=str(ref.session_id), path=rel, length=max_bytes + 1
        )
        data = b"" if info.size > max_bytes else b"".join(chunks)
        if info.size > max_bytes or len(data) > max_bytes:
            raise SandboxFileTooLargeError(
                f"{path!r} is larger than the limit of {max_bytes} bytes"
            )
        return data

    def write_file(self, ref: HarnessSandboxRef, path: str, data: bytes) -> None:
        rel = session_relative_path(ref, path)
        if not rel:
            raise SandboxPathError("cannot write the session directory itself")
        self._session_vm(ref)[1].write_file(
            session_id=str(ref.session_id), path=rel, data=data
        )

    def publish_artifact(
        self, ref: HarnessSandboxRef, path: str, *, display_name: str | None = None
    ) -> str:
        rel = session_relative_path(ref, path)
        data = self.read_file(ref, rel, max_bytes=PUBLISH_MAX_BYTES)
        name = display_name or posixpath.basename(rel)
        # The file store keys and records the file under the context tenant.
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(ref.tenant_id)
        try:
            return get_default_file_store().save_file(
                content=BytesIO(data),
                display_name=name,
                file_origin=FileOrigin.OTHER,
                file_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                file_metadata={
                    "source": "craft_sandbox",
                    "session_id": str(ref.session_id),
                    "path": rel,
                },
            )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
