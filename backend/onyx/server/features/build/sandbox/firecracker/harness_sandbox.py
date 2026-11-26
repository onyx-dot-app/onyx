"""Firecracker implementation of `HarnessSandbox` (`SANDBOX_RUNTIME=firecracker`).

One VM per user sandbox, placed on a host agent node. The shared guest
daemon logic is `DaemonHarnessSandbox`; this module adds the Firecracker
hooks. Each call wakes the VM if needed (placement + wake in `onyx.microvm`)
and runs the guest daemon Init only when the daemon is not initialized. A
session's first use on a VM instance restores its last save through the node
agent (`AgentSessionTransfer`). Exec sessions live in durable cache records
(`harness_state`), so any API pod can serve `write_stdin`. `purge_session`
and `purge_sandbox` delete what a session or a user's sandbox keeps (Onyx
delete hooks call them through `purge`).
"""

import random
import time
from uuid import UUID

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.agent_client import (
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
    MtlsHostAgentClientFactory,
)
from onyx.microvm.configs import SANDBOX_FC_TURN_END_SAVE_INTERVAL_SECONDS
from onyx.microvm.daemon_client import SandboxDaemonClient
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
from onyx.microvm.models import PlacedVm, VmInstance, VmRequest
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
from onyx.server.features.build.sandbox.daemon_harness import (
    DaemonHarnessSandbox,
    RunningInstance,
)
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    last_attempt,
    mark_session_on_instance,
    note_wanted,
    record_attempt,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    AgentSessionTransfer,
    BackgroundIdleStop,
    SessionArchiveStore,
    SessionSaveCheckpointer,
    SessionTransfer,
)
from onyx.server.features.build.sandbox.harness_base import (
    EXEC_DEFAULT_ENV,
    HarnessSandboxError,
)
from onyx.server.features.build.sandbox.models import (
    HarnessSandboxKey,
    HarnessSandboxRef,
    SandboxProvisionContentionError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A wake retries a full node (a node takes a few Creates at a time) or a
# concurrent placement for this long, with backoff and jitter.
WAKE_RETRY_SECONDS = 10.0
# One Init per VM instance across API pods: a second Init resets egress
# connections that a command of the first may already use.
_INIT_LOCK_PREFIX = "sandbox_fc_harness_init:"
_INIT_LOCK_SECONDS = 30.0


class PlacedInstance(RunningInstance):
    """A running VM: its placement and the daemon through its node agent."""

    def __init__(self, placed: PlacedVm, daemon: SandboxDaemonClient) -> None:
        super().__init__(
            daemon=daemon, attempt=placed.vm.attempt, generation=placed.vm.generation
        )
        self.placed = placed


class FirecrackerHarnessSandbox(
    DaemonHarnessSandbox[PlacedInstance], SandboxActivityProbe
):
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
        super().__init__(
            archive_store=archive_store,
            turn_end_save_interval_seconds=turn_end_save_interval_seconds,
        )
        self._template = template
        self._client_factory = client_factory or MtlsHostAgentClientFactory()
        # None: no session saves, so the idle evictor keeps every VM.
        self._archive_store = archive_store
        self.idle_stop = BackgroundIdleStop(self._stop_if_idle)

    # Hooks

    def _instance(self, sandbox: HarnessSandboxKey) -> PlacedInstance:
        return self._placed_instance(self._place(sandbox))

    def _placed_instance(self, placed: PlacedVm) -> PlacedInstance:
        return PlacedInstance(placed, sandbox_daemon(self._client_factory, placed))

    def _instance_if_running(
        self, tenant_cache: CacheBackend, sandbox_id: UUID
    ) -> PlacedInstance | None:
        placed = self._placed_if_running(tenant_cache, sandbox_id)
        return None if placed is None else self._placed_instance(placed)

    def _transfer(self, instance: PlacedInstance) -> SessionTransfer | None:
        if self._archive_store is None:
            return None
        placed = instance.placed
        return AgentSessionTransfer(
            self._client_factory.client(placed.node.address),
            self._archive_store,
            VmInstance(
                sandbox_id=placed.vm.sandbox_id,
                attempt=placed.vm.attempt,
                generation=placed.vm.generation,
                sandboxd_key=placed.sandboxd_key,
            ),
        )

    def _mark_session_set_up(
        self,
        tenant_cache: CacheBackend,
        ref: HarnessSandboxRef,
        instance: PlacedInstance,
    ) -> None:
        with sandbox_placement_lock(tenant_cache, ref.sandbox_id, blocking=True):
            placement = get_sandbox_placement(tenant_cache, ref.sandbox_id)
            if (
                placement is None
                or (placement.attempt, placement.generation) != instance.identity
            ):
                raise HarnessSandboxError(
                    "The sandbox stopped while this session was set up. "
                    "Run the call again."
                )
            mark_session_on_instance(
                tenant_cache, ref.sandbox_id, ref.session_id, instance.identity
            )

    def _forget_sandbox(self, tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
        clear_sandbox_reservation(tenant_cache, sandbox_id)
        clear_sandbox_daemon_key(tenant_cache, sandbox_id)

    def _place(self, sandbox: HarnessSandboxKey) -> PlacedVm:
        """The running, initialized VM. Init runs only when the daemon is not
        initialized: a new boot, a VM adopted from a reservation, or a VM that
        placement replaced after a crash."""
        shared_cache = get_shared_cache_backend()
        tenant_cache = get_cache_backend(tenant_id=sandbox.tenant_id)
        # A stop that saves this sandbox now gives way to this call.
        note_wanted(tenant_cache, sandbox.sandbox_id)
        # The sandbox's attempt record (last_attempt) fences VMs: a placed VM
        # serves any attempt, and a new VM starts past the last one.
        request = VmRequest(
            tenant_id=sandbox.tenant_id,
            sandbox_id=sandbox.sandbox_id,
            attempt=1,
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
                    sandbox.sandbox_id,
                    pause,
                    last_error,
                )
                time.sleep(pause)
                delay = min(delay * 2, 2.0)
            # A stop deletes the placement record, and an agent never creates
            # a stopped attempt again: start past the last one.
            if get_sandbox_placement(tenant_cache, sandbox.sandbox_id) is None:
                floor = last_attempt(tenant_cache, sandbox.sandbox_id) + 1
                if request.attempt < floor:
                    request = request.model_copy(update={"attempt": floor})
            try:
                placed = wake_sandbox_vm(
                    shared_cache, tenant_cache, self._client_factory, request
                )
                if not self._initialized(placed):
                    self._initialize(tenant_cache, sandbox, placed)
                record_attempt(tenant_cache, sandbox.sandbox_id, placed.vm.attempt)
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
        self, tenant_cache: CacheBackend, sandbox: HarnessSandboxKey, placed: PlacedVm
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
                tenant_id=sandbox.tenant_id,
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

    def _stop(
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
