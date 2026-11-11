"""Firecracker implementation of `HarnessSandbox` (`SANDBOX_RUNTIME=firecracker`).

One VM per user sandbox, placed on a host agent node. Each call wakes the VM
if needed (placement + wake in `onyx.microvm`), runs the guest daemon Init
only when the daemon is not initialized, and swaps the managed drive in
before the VM is used. Exec sessions live in durable cache records
(`harness_state`), so any API pod can serve `write_stdin`.
"""

import mimetypes
import posixpath
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Generator, Iterator, Mapping
from io import BytesIO
from uuid import UUID

import grpc
from pydantic import BaseModel, ConfigDict

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend, CacheLockAcquisitionError
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.microvm.agent_client import (
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
    MtlsHostAgentClientFactory,
)
from onyx.microvm.configs import (
    SANDBOX_FC_APPROVAL_PARK_SECONDS,
    SANDBOX_FC_EXEC_DEADLINE_SECONDS,
    SANDBOX_FC_PUBLISH_MAX_BYTES,
    SANDBOX_FC_TURN_LEASE_SECONDS,
)
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.lifecycle import (
    SandboxVmUnusableError,
    initialize_sandbox_vm,
    sandbox_daemon,
    wake_sandbox_vm,
)
from onyx.microvm.models import (
    ExecCommand,
    ExecCompletion,
    ExecGap,
    ExecOutput,
    ExecResult,
    FileType,
    OutputStream,
    PlacedVm,
    VmInstance,
    VmRequest,
)
from onyx.microvm.placement import find_vm, forget_placement, sandbox_placement_lock
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
    ActivityKind,
    ExecSessionRecord,
    add_exec_session,
    clear_activity,
    clear_exec_sessions,
    get_exec_session,
    has_activity,
    list_exec_sessions,
    remove_exec_session,
    set_activity_mark,
    update_exec_session,
)
from onyx.server.features.build.sandbox.harness_base import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    EXEC_DEFAULT_ENV,
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    INTERRUPT_CHAR,
    MAX_EXEC_SESSIONS_PER_SANDBOX,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
    ExecCommandResult,
    ExecEvent,
    ExecOutputDelta,
    ExecSessionEndedError,
    ExecSessionNotFoundError,
    HarnessSandbox,
    HarnessSandboxError,
    HarnessSandboxRef,
    SandboxFile,
    SandboxFileListing,
    SandboxFileTooLargeError,
    SandboxPathError,
    session_workspace,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Daemon execution labels of harness commands.
LABEL_HARNESS = "harness"
LABEL_CHAT_SESSION = "chat_session"
LABEL_EXEC_SESSION = "exec_session"
_HARNESS_LABEL_VALUE = "exec"

_MANAGED_PREFIX = "sandbox_fc:managed_image:"
_EXEC_LOCK_PREFIX = "sandbox_fc:exec_lock:"
# A second call on one exec session waits this long for the first one.
_EXEC_LOCK_WAIT_SECONDS = 30.0
_EXEC_LOCK_MARGIN_SECONDS = 30.0
_INIT_LOCK_PREFIX = "sandbox_fc:init_lock:"
# Covers one daemon Init (attach drives, grow the scratch file system).
_INIT_LOCK_SECONDS = 90.0
# Session directories this process remembers as made.
_PREPARED_MAX = 10_000

# Stop errors that mean the record's instance no longer runs on its node.
_GONE_REASONS: frozenset[HostAgentErrorReason] = frozenset(
    {HostAgentErrorReason.SANDBOX_NOT_FOUND, HostAgentErrorReason.INSTANCE_MISMATCH}
)

_COMPLETION_NAMES: dict[ExecCompletion, str] = {
    ExecCompletion.EXITED: "exited",
    ExecCompletion.SIGNALED: "signaled",
    ExecCompletion.CANCELED: "canceled",
    ExecCompletion.DEADLINE_EXCEEDED: "deadline_exceeded",
}

# The read-only content of the managed drive for a sandbox (a bundle zip),
# or None for no managed drive.
ManagedBundleSource = Callable[[HarnessSandboxRef], bytes | None]


class _ManagedImageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt: int
    generation: int
    image_id: str


class ManagedDriveError(HarnessSandboxError):
    """The managed drive could not be swapped into the VM."""


def _clamp_ms(value: int | None, default: int, low: int, high: int) -> float:
    ms = default if value is None else value
    return min(max(ms, low), high) / 1000.0


def _interrupted_result(started_at: float) -> ExecCommandResult:
    return ExecCommandResult(
        output="",
        exec_session_id=None,
        exit_code=None,
        completion=_COMPLETION_NAMES[ExecCompletion.CANCELED],
        wall_time_seconds=time.monotonic() - started_at,
        original_token_count=0,
        truncated=False,
    )


def _instance(placed: PlacedVm) -> VmInstance:
    return VmInstance(
        sandbox_id=placed.vm.sandbox_id,
        attempt=placed.vm.attempt,
        generation=placed.vm.generation,
        sandboxd_key=placed.sandboxd_key,
    )


def session_relative_path(ref: HarnessSandboxRef, path: str) -> str:
    """The session-relative form of `path` ("" = the session directory).
    Accepts a relative path or an absolute path in the session directory."""
    root = session_workspace(ref.session_id)
    if posixpath.isabs(path):
        normalized = posixpath.normpath(path)
        if normalized == root:
            return ""
        if normalized.startswith(root + "/"):
            return normalized[len(root) + 1 :]
        raise SandboxPathError(
            f"{path!r} is outside the session directory {root}; file calls "
            "only reach the session directory (use exec_command elsewhere)"
        )
    normalized = posixpath.normpath(path) if path else "."
    if normalized == ".":
        return ""
    if normalized == ".." or normalized.startswith("../"):
        raise SandboxPathError(f"{path!r} leaves the session directory")
    return normalized


class FirecrackerHarnessSandbox(HarnessSandbox):
    def __init__(
        self,
        *,
        template: str,
        scratch_gib: int | None = None,
        client_factory: HostAgentClientFactory | None = None,
        init_env: Mapping[str, str] | None = None,
        managed_bundle: ManagedBundleSource | None = None,
        exec_deadline_seconds: float = SANDBOX_FC_EXEC_DEADLINE_SECONDS,
        max_exec_sessions: int = MAX_EXEC_SESSIONS_PER_SANDBOX,
    ) -> None:
        if not template:
            raise ValueError("FirecrackerHarnessSandbox needs a template version")
        self._template = template
        self._scratch_gib = scratch_gib
        self._client_factory = client_factory or MtlsHostAgentClientFactory()
        # Base env of every command. No secrets: the egress proxy injects them.
        self._init_env = {**EXEC_DEFAULT_ENV, **(init_env or {})}
        self._managed_bundle = managed_bundle
        self._exec_deadline_seconds = exec_deadline_seconds
        self._max_exec_sessions = max_exec_sessions
        # (sandbox, attempt, generation, session) whose directory exists,
        # oldest first.
        self._prepared: OrderedDict[tuple[str, int, int, str], None] = OrderedDict()
        self._prepared_lock = threading.Lock()

    # Lifecycle

    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        self._place(ref)

    def _place(self, ref: HarnessSandboxRef) -> PlacedVm:
        shared_cache = get_shared_cache_backend()
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        request = VmRequest(
            tenant_id=ref.tenant_id,
            sandbox_id=ref.sandbox_id,
            attempt=ref.attempt,
            template=self._template,
            scratch_gib=self._scratch_gib,
        )
        try:
            placed = self._wake_and_init(shared_cache, tenant_cache, request)
        except SandboxVmUnusableError as e:
            # The unusable VM is stopped; one more try with the next attempt.
            logger.warning(
                "sandbox_fc_retry_unusable sandbox=%s attempt=%d reason=%s",
                ref.sandbox_id,
                e.attempt,
                e.reason,
            )
            placed = self._wake_and_init(
                shared_cache,
                tenant_cache,
                request.model_copy(update={"attempt": e.attempt}),
            )
        self._ensure_managed(tenant_cache, ref, placed)
        return placed

    def _wake_and_init(
        self,
        shared_cache: CacheBackend,
        tenant_cache: CacheBackend,
        request: VmRequest,
    ) -> PlacedVm:
        placed = wake_sandbox_vm(
            shared_cache, tenant_cache, self._client_factory, request
        )
        daemon = sandbox_daemon(self._client_factory, placed)

        def initialized() -> bool:
            health = daemon.health()
            return health.initialized and health.generation == placed.vm.generation

        # A VM adopted from a reservation can be up without Init. A repeat
        # Init resets the guest's egress connections: run it only when
        # needed, and once across API pods.
        if initialized():
            return placed
        lock = tenant_cache.lock(
            f"{_INIT_LOCK_PREFIX}{placed.vm.sandbox_id}:{placed.vm.generation}",
            timeout=_INIT_LOCK_SECONDS,
        )
        if not lock.acquire(blocking_timeout=_INIT_LOCK_SECONDS):
            raise CacheLockAcquisitionError(placed.vm.sandbox_id)
        try:
            if initialized():
                return placed
            initialize_sandbox_vm(
                shared_cache,
                tenant_cache,
                self._client_factory,
                placed,
                tenant_id=request.tenant_id,
                env=self._init_env,
                session_ids=[],
            )
        finally:
            if lock.owned():
                lock.release()
        return placed

    def _ensure_managed(
        self, tenant_cache: CacheBackend, ref: HarnessSandboxRef, placed: PlacedVm
    ) -> None:
        """Swap the managed drive into a VM instance once, before first use."""
        if self._managed_bundle is None:
            return
        key = _MANAGED_PREFIX + str(ref.sandbox_id)
        raw = tenant_cache.get(key)
        if raw is not None:
            record = _ManagedImageRecord.model_validate_json(raw)
            if (record.attempt, record.generation) == (
                placed.vm.attempt,
                placed.vm.generation,
            ):
                return
        self.refresh_managed(ref, placed=placed)

    def refresh_managed(
        self, ref: HarnessSandboxRef, *, placed: PlacedVm | None = None
    ) -> None:
        """Build the managed bundle again and swap it into the running VM
        (for example after the user's skills changed)."""
        if self._managed_bundle is None:
            return
        placed = placed or self._place(ref)
        bundle = self._managed_bundle(ref)
        if bundle is None:
            return
        client = self._client_factory.client(placed.node.address)
        image = client.put_managed_image(bundle).image
        [result] = client.swap_managed(
            image_id=image.image_id, targets=[_instance(placed)]
        )
        if not result.ok:
            raise ManagedDriveError(
                f"managed drive swap failed: {result.reason} {result.message}"
            )
        get_cache_backend(tenant_id=ref.tenant_id).set(
            _MANAGED_PREFIX + str(ref.sandbox_id),
            _ManagedImageRecord(
                attempt=placed.vm.attempt,
                generation=placed.vm.generation,
                image_id=image.image_id,
            ).model_dump_json(),
        )

    def _placed_if_running(
        self, tenant_id: str, sandbox_id: UUID, timeout: float | None = None
    ) -> PlacedVm | None:
        """The placed VM when it runs, without starting one. Raises the agent
        and daemon errors of List."""
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None:
            return None
        node = get_registered_node(get_shared_cache_backend(), placement.node_id)
        if node is None:
            return None
        vms = self._client_factory.client(node.address).list_vms(timeout=timeout)
        vm = find_vm(vms, sandbox_id, placement.generation)
        if vm is None or vm.attempt != placement.attempt or not vm.state.is_live():
            return None
        key = get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt)
        if key is None:
            return None
        return PlacedVm(node=node, vm=vm, created=False, sandboxd_key=key)

    def health(self, *, tenant_id: str, sandbox_id: UUID, timeout: float) -> bool:
        """True when the placed VM runs and its daemon is initialized. Never
        starts a VM."""
        try:
            placed = self._placed_if_running(tenant_id, sandbox_id, timeout)
            if placed is None:
                return False
            health = sandbox_daemon(self._client_factory, placed).health(
                timeout=timeout
            )
        except (HostAgentError, SandboxDaemonError):
            logger.warning(
                "sandbox_fc_health_failed sandbox=%s", sandbox_id, exc_info=True
            )
            return False
        return (
            health.initialized
            and health.key_set
            and health.generation == placed.vm.generation
        )

    def terminate(self, *, tenant_id: str, sandbox_id: UUID) -> None:
        """Stop the placed VM now, with no save (the caller owns saves), and
        clear its records. A VM on a node that is gone from the registry is
        stopped later as an orphan, when that node reports again."""
        shared_cache = get_shared_cache_backend()
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=True):
            placement = get_sandbox_placement(tenant_cache, sandbox_id)
            if placement is not None:
                node = get_registered_node(shared_cache, placement.node_id)
                if node is not None:
                    try:
                        self._client_factory.client(node.address).stop(
                            sandbox_id=str(sandbox_id),
                            attempt=placement.attempt,
                            generation=placement.generation,
                        )
                    except HostAgentError as e:
                        if e.reason not in _GONE_REASONS:
                            raise
                forget_placement(
                    shared_cache,
                    tenant_cache,
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    node_id=placement.node_id,
                    attempt=placement.attempt,
                    generation=placement.generation,
                )
                logger.info(
                    "sandbox_fc_terminated node=%s sandbox=%s attempt=%d generation=%d",
                    placement.node_id,
                    sandbox_id,
                    placement.attempt,
                    placement.generation,
                )
            clear_exec_sessions(tenant_cache, sandbox_id)
            clear_activity(tenant_cache, sandbox_id)
            tenant_cache.delete(_MANAGED_PREFIX + str(sandbox_id))

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
        set_activity_mark(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            ref.session_id,
            kind=ActivityKind.TURN,
            ttl_seconds=SANDBOX_FC_TURN_LEASE_SECONDS,
        )
        self.touch(ref)

    def end_turn(self, ref: HarnessSandboxRef) -> None:
        set_activity_mark(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            ref.session_id,
            kind=ActivityKind.TURN,
            ttl_seconds=None,
        )
        self.touch(ref)

    def set_approval_parked(self, ref: HarnessSandboxRef, parked: bool) -> None:
        set_activity_mark(
            get_cache_backend(tenant_id=ref.tenant_id),
            ref.sandbox_id,
            ref.session_id,
            kind=ActivityKind.APPROVAL,
            ttl_seconds=SANDBOX_FC_APPROVAL_PARK_SECONDS if parked else None,
        )

    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:
        if has_activity(get_cache_backend(tenant_id=tenant_id), sandbox_id):
            return True
        try:
            placed = self._placed_if_running(tenant_id, sandbox_id)
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

    def _daemon(self, placed: PlacedVm) -> SandboxDaemonClient:
        return sandbox_daemon(self._client_factory, placed)

    def _prepare_session_dir(
        self, daemon: SandboxDaemonClient, placed: PlacedVm, session_id: UUID
    ) -> None:
        key = (
            placed.vm.sandbox_id,
            placed.vm.attempt,
            placed.vm.generation,
            str(session_id),
        )
        with self._prepared_lock:
            if key in self._prepared:
                self._prepared.move_to_end(key)
                return
        directory = session_workspace(session_id)
        events = list(daemon.run(ExecCommand(argv=["mkdir", "-p", directory])))
        result = events[-1]
        if not isinstance(result, ExecResult) or result.exit_code != 0:
            raise HarnessSandboxError(f"could not create {directory}")
        with self._prepared_lock:
            self._prepared[key] = None
            while len(self._prepared) > _PREPARED_MAX:
                self._prepared.popitem(last=False)

    def _workdir(self, ref: HarnessSandboxRef, workdir: str | None) -> str:
        """The absolute working directory (default: the session directory)."""
        if not workdir:
            return session_workspace(ref.session_id)
        if posixpath.isabs(workdir):
            return posixpath.normpath(workdir)
        return posixpath.normpath(
            posixpath.join(session_workspace(ref.session_id), workdir)
        )

    def _ended_executions(self, daemon: SandboxDaemonClient) -> set[str]:
        return {
            e.execution_id
            for e in daemon.list_executions({LABEL_HARNESS: _HARNESS_LABEL_VALUE})
            if e.result is not None
        }

    def _cancel_evicted(
        self, daemon: SandboxDaemonClient, evicted: list[ExecSessionRecord]
    ) -> None:
        for record in evicted:
            try:
                daemon.cancel(record.execution_id)
            except (HostAgentError, SandboxDaemonError):
                logger.warning(
                    "sandbox_fc_exec_evict_cancel_failed execution=%s",
                    record.execution_id,
                    exc_info=True,
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
        return self._exec_command(
            ref,
            cmd,
            workdir=workdir,
            yield_seconds=_clamp_ms(
                yield_time_ms,
                EXEC_DEFAULT_YIELD_MS,
                EXEC_MIN_YIELD_MS,
                EXEC_MAX_YIELD_MS,
            ),
            max_output_tokens=max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def _exec_command(
        self,
        ref: HarnessSandboxRef,
        cmd: str,
        *,
        workdir: str | None,
        yield_seconds: float,
        max_output_tokens: int,
    ) -> Generator[ExecEvent, None, None]:
        started_at = time.monotonic()
        placed = self._place(ref)
        daemon = self._daemon(placed)
        self._prepare_session_dir(daemon, placed, ref.session_id)
        cwd = self._workdir(ref, workdir)
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        exec_session_id = secrets.token_hex(4)
        started = daemon.start(
            ExecCommand(
                argv=["bash", "-c", cmd],
                cwd=cwd,
                env=dict(EXEC_DEFAULT_ENV),
                stdin=True,
                deadline_seconds=self._exec_deadline_seconds,
                labels={
                    LABEL_HARNESS: _HARNESS_LABEL_VALUE,
                    LABEL_CHAT_SESSION: str(ref.session_id),
                    LABEL_EXEC_SESSION: exec_session_id,
                },
            )
        )
        record = ExecSessionRecord(
            exec_session_id=exec_session_id,
            chat_session_id=str(ref.session_id),
            execution_id=started.execution_id,
            attempt=placed.vm.attempt,
            generation=placed.vm.generation,
            last_used=time.time(),
        )
        # Only a full table needs the daemon's view of which commands ended.
        live = [
            r
            for r in list_exec_sessions(tenant_cache, ref.sandbox_id)
            if r.on_instance(record.attempt, record.generation)
        ]
        ended = (
            self._ended_executions(daemon)
            if len(live) >= self._max_exec_sessions
            else set()
        )
        try:
            evicted = add_exec_session(
                tenant_cache,
                ref.sandbox_id,
                record,
                max_sessions=self._max_exec_sessions,
                ended_execution_ids=ended,
            )
        except Exception:
            # Without a record nobody can reach the command: stop it.
            self._cancel_evicted(daemon, [record])
            raise
        if evicted is None:
            # The VM was replaced during this call.
            self._cancel_evicted(daemon, [record])
            raise ExecSessionEndedError(exec_session_id)
        self._cancel_evicted(
            daemon, [r for r in evicted if r.execution_id not in ended]
        )
        yield from self._collect(
            tenant_cache,
            ref,
            daemon,
            record,
            until=started_at + yield_seconds,
            started_at=started_at,
            max_output_tokens=max_output_tokens,
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
        return self._write_stdin(
            ref,
            exec_session_id,
            chars,
            yield_seconds=yield_seconds,
            max_output_tokens=max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        )

    def _write_stdin(
        self,
        ref: HarnessSandboxRef,
        exec_session_id: str,
        chars: str,
        *,
        yield_seconds: float,
        max_output_tokens: int,
    ) -> Generator[ExecEvent, None, None]:
        started_at = time.monotonic()
        tenant_cache = get_cache_backend(tenant_id=ref.tenant_id)
        record = get_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
        if record is None or record.chat_session_id != str(ref.session_id):
            raise ExecSessionNotFoundError(exec_session_id)
        placed = self._place(ref)
        if not record.on_instance(placed.vm.attempt, placed.vm.generation):
            remove_exec_session(
                tenant_cache,
                ref.sandbox_id,
                exec_session_id,
                execution_id=record.execution_id,
            )
            raise ExecSessionEndedError(exec_session_id)
        daemon = self._daemon(placed)
        # Write and interrupt before the read lock: a long poll by another
        # call must not hold back a Ctrl-C.
        text, interrupt, _ = chars.partition(INTERRUPT_CHAR)
        try:
            if text:
                daemon.interact(record.execution_id, data=text.encode())
            if interrupt:
                daemon.cancel(record.execution_id)
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND:
                self._forget(tenant_cache, ref, record)
                raise ExecSessionEndedError(exec_session_id) from e
            # An ended command: report its result below.
            if e.reason is not SandboxDaemonErrorReason.EXECUTION_ENDED:
                raise
        lock = tenant_cache.lock(
            f"{_EXEC_LOCK_PREFIX}{ref.sandbox_id}:{exec_session_id}",
            timeout=yield_seconds + _EXEC_LOCK_MARGIN_SECONDS,
        )
        if not lock.acquire(blocking_timeout=_EXEC_LOCK_WAIT_SECONDS):
            if interrupt:
                # Another call reads the output; the interrupt is done.
                yield _interrupted_result(started_at)
                return
            raise CacheLockAcquisitionError(exec_session_id)
        try:
            # Read the offsets again: the call before this one moved them.
            current = get_exec_session(tenant_cache, ref.sandbox_id, exec_session_id)
            if current is None or current.execution_id != record.execution_id:
                if interrupt:
                    # Another call already reported the end.
                    yield _interrupted_result(started_at)
                    return
                raise ExecSessionNotFoundError(exec_session_id)
            yield from self._collect(
                tenant_cache,
                ref,
                daemon,
                current,
                until=started_at + yield_seconds,
                started_at=started_at,
                max_output_tokens=max_output_tokens,
            )
        finally:
            if lock.owned():
                lock.release()

    def _forget(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        record: ExecSessionRecord,
    ) -> None:
        remove_exec_session(
            tenant_cache,
            ref.sandbox_id,
            record.exec_session_id,
            execution_id=record.execution_id,
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
    ) -> Generator[ExecEvent, None, None]:
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
                if isinstance(event, ExecOutput):
                    skip = max(offsets[event.stream] - event.offset, 0)
                    data = event.data[skip:]
                    offsets[event.stream] = max(
                        offsets[event.stream], event.offset + len(event.data)
                    )
                    text = buffer.add(event.stream, data)
                    if text:
                        yield ExecOutputDelta(text=text)
                elif isinstance(event, ExecGap):
                    if event.end > offsets[event.stream]:
                        lost = event.end - max(offsets[event.stream], event.start)
                        offsets[event.stream] = event.end
                        text = buffer.add_gap(event.stream, lost)
                        if text:
                            yield ExecOutputDelta(text=text)
                elif isinstance(event, ExecResult):
                    result = event
        except HostAgentError as e:
            # The yield time passed while the command runs.
            if e.reached_agent or e.code is not grpc.StatusCode.DEADLINE_EXCEEDED:
                raise
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_NOT_FOUND:
                self._forget(tenant_cache, ref, record)
                raise ExecSessionEndedError(record.exec_session_id) from e
            raise
        if result is None:
            update_exec_session(
                tenant_cache,
                ref.sandbox_id,
                record.exec_session_id,
                execution_id=record.execution_id,
                stdout_offset=offsets[OutputStream.STDOUT],
                stderr_offset=offsets[OutputStream.STDERR],
            )
        else:
            self._forget(tenant_cache, ref, record)
        full = buffer.text()
        output, cut = cut_to_tokens(full, max_output_tokens)
        yield ExecCommandResult(
            output=output,
            exec_session_id=None if result is not None else record.exec_session_id,
            exit_code=(
                result.exit_code
                if result is not None and result.completion is ExecCompletion.EXITED
                else None
            ),
            completion=(
                _COMPLETION_NAMES.get(result.completion, "unknown")
                if result is not None
                else None
            ),
            wall_time_seconds=time.monotonic() - started_at,
            original_token_count=estimate_tokens(full),
            truncated=cut or buffer.truncated,
        )

    # Files (paths relative to the session directory)

    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        rel = session_relative_path(ref, path)
        daemon = self._daemon(self._place(ref))
        info, chunks = daemon.read_file(session_id=str(ref.session_id), path=rel)
        if info.size > max_bytes:
            # Start, then close the chunk generator: its cleanup cancels
            # the stream (an unstarted generator skips it).
            for _ in chunks:
                break
            if isinstance(chunks, Generator):
                chunks.close()
            raise SandboxFileTooLargeError(
                f"{path!r} has {info.size} bytes; the limit is {max_bytes}"
            )
        data = bytearray()
        for chunk in chunks:
            data += chunk
            if len(data) > max_bytes:
                raise SandboxFileTooLargeError(
                    f"{path!r} grew past the limit of {max_bytes} bytes"
                )
        return bytes(data)

    def write_file(self, ref: HarnessSandboxRef, path: str, data: bytes) -> None:
        rel = session_relative_path(ref, path)
        if not rel:
            raise SandboxPathError("cannot write the session directory itself")
        self._daemon(self._place(ref)).write_file(
            session_id=str(ref.session_id), path=rel, data=data
        )

    def list_files(
        self, ref: HarnessSandboxRef, path: str = "", *, recursive: bool = False
    ) -> SandboxFileListing:
        rel = session_relative_path(ref, path)
        listing = self._daemon(self._place(ref)).list_files(
            session_id=str(ref.session_id), path=rel, recursive=recursive
        )
        return SandboxFileListing(
            entries=[
                SandboxFile(
                    path=e.path,
                    name=e.name,
                    is_directory=e.type is FileType.DIRECTORY,
                    size=e.size,
                    modified_at=e.modified_at,
                )
                for e in listing.entries
            ],
            truncated=listing.truncated,
        )

    def delete_file(
        self, ref: HarnessSandboxRef, path: str, *, recursive: bool = False
    ) -> bool:
        rel = session_relative_path(ref, path)
        if not rel:
            raise SandboxPathError("cannot delete the session directory itself")
        return self._daemon(self._place(ref)).delete_file(
            session_id=str(ref.session_id), path=rel, recursive=recursive
        )

    def publish_artifact(
        self, ref: HarnessSandboxRef, path: str, *, display_name: str | None = None
    ) -> str:
        rel = session_relative_path(ref, path)
        data = self.read_file(ref, rel, max_bytes=SANDBOX_FC_PUBLISH_MAX_BYTES)
        name = display_name or posixpath.basename(rel)
        file_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return get_default_file_store().save_file(
            content=BytesIO(data),
            display_name=name,
            file_origin=FileOrigin.OTHER,
            file_type=file_type,
            file_metadata={
                "source": "craft_sandbox",
                "session_id": str(ref.session_id),
                "path": rel,
            },
        )
