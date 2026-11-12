"""Firecracker implementation of `HarnessSandbox` (`SANDBOX_RUNTIME=firecracker`).

One VM per user sandbox, placed on a host agent node. Each call wakes the VM
if needed (placement + wake in `onyx.microvm`) and runs the guest daemon Init
only when the daemon is not initialized. Exec sessions live in durable cache
records (`harness_state`), so any API pod can serve `write_stdin`.
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
    SandboxVmUnusableError,
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
    VmRequest,
)
from onyx.microvm.placement import find_vm
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
    put_exec_session,
    remove_exec_session,
    set_mark,
)
from onyx.server.features.build.sandbox.firecracker.models import ExecSessionRecord
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


class FirecrackerHarnessSandbox(HarnessSandbox):
    def __init__(
        self,
        *,
        template: str,
        client_factory: HostAgentClientFactory | None = None,
    ) -> None:
        if not template:
            raise ValueError("FirecrackerHarnessSandbox needs a template image tag")
        self._template = template
        self._client_factory = client_factory or MtlsHostAgentClientFactory()

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
        while True:
            try:
                placed = wake_sandbox_vm(
                    shared_cache, tenant_cache, self._client_factory, request
                )
                health = sandbox_daemon(self._client_factory, placed).health()
                if not health.initialized or health.generation != placed.vm.generation:
                    initialize_sandbox_vm(
                        shared_cache,
                        tenant_cache,
                        self._client_factory,
                        placed,
                        tenant_id=ref.tenant_id,
                        # No secrets: the egress proxy injects them.
                        env=dict(EXEC_DEFAULT_ENV),
                        session_ids=[],
                    )
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
                pause = random.uniform(delay / 2, delay)
                if time.monotonic() + pause > give_up_at:
                    raise
                logger.info(
                    "sandbox_fc_wake_retry sandbox=%s pause=%.2f error=%s",
                    ref.sandbox_id,
                    pause,
                    e,
                )
                time.sleep(pause)
                delay = min(delay * 2, 2.0)

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
        placed = self._place(ref)
        daemon = sandbox_daemon(self._client_factory, placed)
        try:
            # The daemon makes the session directory, the default cwd.
            started = daemon.start(
                ExecCommand(
                    argv=["bash", "-c", cmd],
                    cwd=workdir or "",
                    stdin=True,
                    deadline_seconds=EXEC_DEADLINE_SECONDS,
                    session_id=str(ref.session_id),
                )
            )
        except SandboxDaemonError as e:
            if e.reason is SandboxDaemonErrorReason.EXECUTION_CAP_REACHED:
                raise ExecCapReachedError() from e
            raise
        record = ExecSessionRecord(
            exec_session_id=secrets.token_hex(4),
            chat_session_id=str(ref.session_id),
            execution_id=started.execution_id,
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
        daemon = sandbox_daemon(self._client_factory, self._place(ref))
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
        sandbox_daemon(self._client_factory, self._place(ref)).write_file(
            session_id=str(ref.session_id), path=rel, data=data
        )

    def publish_artifact(
        self, ref: HarnessSandboxRef, path: str, *, display_name: str | None = None
    ) -> str:
        rel = session_relative_path(ref, path)
        data = self.read_file(ref, rel, max_bytes=PUBLISH_MAX_BYTES)
        name = display_name or posixpath.basename(rel)
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
