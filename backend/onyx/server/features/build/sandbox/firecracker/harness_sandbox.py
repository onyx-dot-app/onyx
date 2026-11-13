"""Firecracker implementation of `HarnessSandbox` (`SANDBOX_RUNTIME=firecracker`).

One VM per user sandbox, placed on a host agent node. Each call wakes the VM
if needed (placement + wake in `onyx.microvm`) and runs the guest daemon Init
only when the daemon is not initialized. A session's first use on a VM
instance restores its last save (`session_saves`). Exec sessions live in
durable cache records (`harness_state`), so any API pod can serve
`write_stdin`. `purge_session` and `purge_sandbox` delete what a session or
a user's sandbox keeps (Onyx delete hooks call them through `purge`).
"""

import mimetypes
import posixpath
import random
import secrets
import time
from collections.abc import Iterator
from io import BytesIO
from uuid import UUID

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import FileOrigin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.microvm.agent_client import (
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
    MtlsHostAgentClientFactory,
)
from onyx.microvm.configs import SANDBOX_FC_TURN_END_SAVE_INTERVAL_SECONDS
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
from onyx.microvm.placement import find_vm, forget_placement, sandbox_placement_lock
from onyx.microvm.registry import (
    clear_sandbox_daemon_key,
    clear_sandbox_reservation,
    get_registered_node,
    get_sandbox_daemon_key,
    get_sandbox_placement,
    is_node_draining,
    touch_sandbox_placement,
)
from onyx.server.features.build.sandbox.exec_output import (
    ExecOutputBuffer,
    cut_to_tokens,
    estimate_tokens,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    ARTIFACTS_PREFIX,
    EXEC_SESSIONS_PREFIX,
    SANDBOX_STATE_PREFIXES,
    SAVED_SESSIONS_PREFIX,
    SESSION_INSTANCES_PREFIX,
    add_id,
    forget_session_on_instances,
    get_exec_session,
    get_ids,
    get_session_save,
    has_marks,
    last_attempt,
    mark_purged,
    mark_session_on_instance,
    note_wanted,
    put_exec_session,
    record_attempt,
    remove_exec_session,
    remove_id,
    sessions_on_instance,
    set_mark,
)
from onyx.server.features.build.sandbox.firecracker.models import (
    ExecSessionRecord,
    ExecSessionTable,
    SessionInstanceTable,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    BackgroundIdleStop,
    BackgroundTurnSave,
    SessionArchiveStore,
    SessionSaveCheckpointer,
    SessionSaveError,
    delete_session_archives,
    restore_session,
    save_session,
    session_save_lock,
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
        turn_end_save_interval_seconds: int = SANDBOX_FC_TURN_END_SAVE_INTERVAL_SECONDS,
    ) -> None:
        if not template:
            raise ValueError("FirecrackerHarnessSandbox needs a template image tag")
        self._template = template
        self._client_factory = client_factory or MtlsHostAgentClientFactory()
        # None: no session saves, so the idle evictor keeps every VM.
        self._archive_store = archive_store
        self._turn_end_save_interval = turn_end_save_interval_seconds
        self.idle_stop = BackgroundIdleStop(self._stop_if_idle)
        self.turn_save = BackgroundTurnSave(self._save_after_turn)

    # Lifecycle

    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        self._place(ref)

    def _place(self, ref: HarnessSandboxRef) -> PlacedVm:
        """The running, initialized VM. Init runs only when the daemon is not
        initialized: a new boot, a VM adopted from a reservation, or a VM that
        placement replaced after a crash."""
        shared_cache = get_shared_cache_backend()
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        # A stop that saves this sandbox now gives way to this call.
        note_wanted(tenant_cache, ref.sandbox_id)
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
        if self._archive_store is not None and self._turn_end_save_interval:
            self.turn_save.submit(ref)

    def _save_after_turn(self, ref: HarnessSandboxRef) -> None:
        """Save the session on its running VM, unless a new turn began, its
        last save is recent, or another save of it runs. Never starts the VM
        and never blocks a call."""
        store = self._archive_store
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
        placed = self._placed_if_running(tenant_cache, ref.sandbox_id)
        if placed is None:
            return
        # Only a session restored on this instance: a save of a session that
        # was never set up here would replace its last save with less.
        if ref.session_id not in sessions_on_instance(
            tenant_cache, ref.sandbox_id, (placed.vm.attempt, placed.vm.generation)
        ):
            return
        with session_save_lock(tenant_cache, ref.session_id) as held:
            if not held:
                return
            with tenant_scope(ref.tenant_id):
                save_session(
                    tenant_cache,
                    self._client_factory.client(placed.node.address),
                    sandbox_daemon(self._client_factory, placed),
                    store,
                    VmInstance(
                        sandbox_id=placed.vm.sandbox_id,
                        attempt=placed.vm.attempt,
                        generation=placed.vm.generation,
                        sandboxd_key=placed.sandboxd_key,
                    ),
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
        """The running VM and its daemon, with the session's last save
        restored once per VM instance. Uses no command slot."""
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
        shared_cache = get_shared_cache_backend()
        return evict_idle_sandbox_vm(
            shared_cache,
            tenant_cache,
            self._client_factory,
            checkpointer,
            self,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            last_active=placement.last_active,
            now=int(time.time()),
            draining=is_node_draining(shared_cache, placement.node_id),
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
                window_seconds=max(until - time.monotonic(), 0.001),
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
        with tenant_scope(ref.tenant_id):
            file_id = get_default_file_store().save_file(
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
        # A session delete keeps artifacts; a sandbox purge deletes them.
        try:
            add_id(
                get_cache_backend(tenant_id=ref.tenant_id),
                ARTIFACTS_PREFIX,
                ref.sandbox_id,
                file_id,
            )
        except Exception:
            # The file is saved; only a later sandbox purge misses it.
            logger.warning(
                "sandbox_fc_artifact_index_failed sandbox=%s file=%s",
                ref.sandbox_id,
                file_id,
                exc_info=True,
            )
        return file_id

    # Purge (delete hooks). Each step runs even when an earlier one failed;
    # the call raises at the end if any step failed.

    def purge_session(
        self, *, tenant_id: str, sandbox_id: UUID, session_id: UUID
    ) -> None:
        """Delete a chat session's save, its directory on the running VM and
        its exec records. Its published artifacts stay."""
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        mark_purged(tenant_cache, session_id=session_id)
        errors: list[Exception] = []
        try:
            placed = self._placed_if_running(tenant_cache, sandbox_id)
            if placed is not None:
                self._cancel_session_commands(
                    tenant_cache, placed, sandbox_id, session_id
                )
                # The VM-wide path: a session-relative call cannot delete
                # the session directory itself.
                sandbox_daemon(self._client_factory, placed).delete_file(
                    session_id="", path=session_workspace(session_id), recursive=True
                )
        except Exception as e:
            # The directory goes with the VM at its next stop.
            errors.append(e)
        try:
            forget_session_on_instances(tenant_cache, sandbox_id, session_id)
        except Exception as e:
            errors.append(e)
        try:
            with tenant_scope(tenant_id):
                delete_session_archives(
                    tenant_cache, self._archive_store, sandbox_id, session_id
                )
        except Exception as e:
            errors.append(e)
        _raise_first(errors, f"session {session_id}")
        logger.info(
            "sandbox_fc_session_purged sandbox=%s session=%s", sandbox_id, session_id
        )

    def _cancel_session_commands(
        self,
        tenant_cache: CacheBackend,
        placed: PlacedVm,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> None:
        daemon = sandbox_daemon(self._client_factory, placed)
        table = ExecSessionTable.model_validate_json(
            tenant_cache.get(EXEC_SESSIONS_PREFIX + str(sandbox_id)) or b"{}"
        )
        for record in table.sessions.values():
            if record.chat_session_id != str(session_id):
                continue
            if (record.attempt, record.generation) == (
                placed.vm.attempt,
                placed.vm.generation,
            ):
                try:
                    daemon.cancel(record.execution_id)
                except (HostAgentError, SandboxDaemonError):
                    # The command stops with the VM at the latest.
                    pass
            remove_exec_session(tenant_cache, sandbox_id, record.exec_session_id)

    def purge_sandbox(self, *, tenant_id: str, sandbox_id: UUID) -> None:
        """Stop the sandbox's VM (the agent deletes its disk) and delete
        every save, artifact and record of the sandbox."""
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        mark_purged(tenant_cache, sandbox_id=sandbox_id)
        # A stop that saves the sandbox now gives way to the purge.
        note_wanted(tenant_cache, sandbox_id)
        errors: list[Exception] = []
        try:
            self._stop_for_purge(tenant_id, tenant_cache, sandbox_id)
        except Exception as e:
            # With no record left, the node report stops the VM as an orphan.
            errors.append(e)
        instances = SessionInstanceTable.model_validate_json(
            tenant_cache.get(SESSION_INSTANCES_PREFIX + str(sandbox_id)) or b"{}"
        )
        sessions = set(get_ids(tenant_cache, SAVED_SESSIONS_PREFIX, sandbox_id))
        with tenant_scope(tenant_id):
            for session_id in sorted(sessions | set(instances.sessions)):
                try:
                    delete_session_archives(
                        tenant_cache, self._archive_store, sandbox_id, UUID(session_id)
                    )
                except Exception as e:
                    errors.append(e)
            for file_id in get_ids(tenant_cache, ARTIFACTS_PREFIX, sandbox_id):
                try:
                    get_default_file_store().delete_file(
                        file_id, error_on_missing=False
                    )
                    remove_id(tenant_cache, ARTIFACTS_PREFIX, sandbox_id, file_id)
                except Exception as e:
                    errors.append(e)
        clear_sandbox_reservation(tenant_cache, sandbox_id)
        clear_sandbox_daemon_key(tenant_cache, sandbox_id)
        # The saved-session and artifact indexes keep what failed, for a retry.
        for prefix in SANDBOX_STATE_PREFIXES:
            tenant_cache.delete(prefix + str(sandbox_id))
        _raise_first(errors, f"sandbox {sandbox_id}")
        logger.info("sandbox_fc_sandbox_purged sandbox=%s", sandbox_id)

    def _stop_for_purge(
        self, tenant_id: str, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> None:
        try:
            with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=True):
                self._stop_and_forget(tenant_id, tenant_cache, sandbox_id)
        except SandboxProvisionContentionError:
            # A purge does not wait for a stuck lock holder. A placement that
            # ends after this can leave a VM; the purge mark keeps it unsaved.
            logger.warning("sandbox_fc_purge_without_lock sandbox=%s", sandbox_id)
            self._stop_and_forget(tenant_id, tenant_cache, sandbox_id)

    def _stop_and_forget(
        self, tenant_id: str, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> None:
        """Stop the placed VM, and clear its record even when the Stop fails
        (the node report then stops the VM as an orphan)."""
        shared_cache = get_shared_cache_backend()
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None:
            return
        try:
            node = get_registered_node(shared_cache, placement.node_id)
            if node is not None:
                try:
                    self._client_factory.client(node.address).stop(
                        sandbox_id=str(sandbox_id),
                        attempt=placement.attempt,
                        generation=placement.generation,
                    )
                except HostAgentError as e:
                    if e.reason not in (
                        HostAgentErrorReason.SANDBOX_NOT_FOUND,
                        HostAgentErrorReason.INSTANCE_MISMATCH,
                    ):
                        raise
        finally:
            forget_placement(
                shared_cache,
                tenant_cache,
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                node_id=placement.node_id,
                attempt=placement.attempt,
                generation=placement.generation,
            )


def _raise_first(errors: list[Exception], what: str) -> None:
    if errors:
        for e in errors[1:]:
            logger.warning("sandbox_fc_purge_step_failed %s: %s", what, e)
        raise errors[0]
