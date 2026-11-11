"""Firecracker sandbox VM lifecycle (ENG-4576): wake, activity, stop, idle eviction.

- Wake (P5): `wake_sandbox_vm` is the only entry that starts a VM. Call it from
  the first tool call that needs the sandbox; nothing pre-warms. It is an
  idempotent ensure (see `place_sandbox_vm`).
- Activity: `touch_sandbox_vm` sets the record's `last_active`. The record has
  no TTL, so activity only feeds the idle evictor.
- Stop: never without a saved checkpoint, and the VM's liveness is checked
  again right before the Stop call.
- Idle evictor (API side, like E2B's): a node report checks each running VM's
  `last_active` against `SANDBOX_FC_IDLE_TIMEOUT_SECONDS` (P4), and stops it
  only when nothing runs in it (P7) and a checkpoint is saved.
- Init: `initialize_sandbox_vm` closes the VM's relay connections and runs the
  guest daemon Init with the VM's key. A daemon without the key makes the VM
  unusable: it is stopped, and the caller wakes the next attempt.

Until session saves (ENG-4580) and the daemon's execution report (ENG-4575)
exist, the defaults (`NoCheckpointSupport`, `UnknownActivity`) keep every VM.
"""

import abc
import random
import time
from enum import Enum
from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.microvm.agent_client import (
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
)
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.daemon_client import SandboxDaemonClient, SandboxDaemonError
from onyx.microvm.models import AgentVm, DaemonInitResult, PlacedVm, VmRequest
from onyx.microvm.placement import (
    discard_unusable_vm,
    find_vm,
    forget_placement,
    place_sandbox_vm,
    sandbox_placement_lock,
)
from onyx.microvm.registry import (
    get_registered_node,
    get_sandbox_placement,
    touch_sandbox_placement,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SandboxCheckpointer(abc.ABC):
    """Saves the session state of a VM before the VM may be stopped."""

    # False: no VM is stopped automatically, so callers skip the agent calls.
    supported: bool = True

    @abc.abstractmethod
    def save_checkpoint(self, *, tenant_id: str, sandbox_id: UUID, vm: AgentVm) -> bool:
        """True only when the VM's state is saved and committed."""
        raise NotImplementedError


class NoCheckpointSupport(SandboxCheckpointer):
    """No session saves yet (ENG-4580): no VM is ever stopped automatically."""

    supported = False

    def save_checkpoint(self, *, tenant_id: str, sandbox_id: UUID, vm: AgentVm) -> bool:  # noqa: ARG002
        return False


class SandboxActivityProbe(abc.ABC):
    @abc.abstractmethod
    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:
        """True while a turn, an approval or a command runs in the sandbox."""
        raise NotImplementedError


class UnknownActivity(SandboxActivityProbe):
    """No execution report yet (ENG-4575): every sandbox counts as busy."""

    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:  # noqa: ARG002
        return True


class VmStopOutcome(str, Enum):
    STOPPED = "stopped"
    # The record named no live VM; the record is cleared.
    ALREADY_GONE = "already_gone"
    NOT_PLACED = "not_placed"
    NOT_IDLE = "not_idle"
    KEPT_BUSY = "kept_busy"
    KEPT_NO_CHECKPOINT = "kept_no_checkpoint"
    # The node did not answer; nothing changed.
    NODE_UNREACHABLE = "node_unreachable"
    # Another placement, stop or reconcile holds the sandbox lock.
    LOCKED = "locked"


def wake_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    rng: random.Random | None = None,
) -> PlacedVm:
    """Return the sandbox's running VM, starting it if needed.

    The Firecracker sandbox manager (ENG-4575) calls this only on the first
    tool call that needs the sandbox. Errors: see `place_sandbox_vm`.
    """
    return place_sandbox_vm(shared_cache, tenant_cache, client_factory, request, rng)


class SandboxVmUnusableError(Exception):
    """The guest daemon has no key or another key. The VM is stopped; wake
    the sandbox again with `attempt` (the next attempt)."""

    def __init__(self, sandbox_id: UUID, attempt: int, reason: str) -> None:
        super().__init__(f"sandbox {sandbox_id} VM is unusable ({reason})")
        self.sandbox_id = sandbox_id
        self.attempt = attempt
        self.reason = reason


def sandbox_daemon(
    client_factory: HostAgentClientFactory, placed: PlacedVm
) -> SandboxDaemonClient:
    """The guest daemon of a placed VM, through its agent's pass-through."""
    return SandboxDaemonClient(
        client_factory.client(placed.node.address).channel,
        sandbox_id=placed.vm.sandbox_id,
        sandboxd_key=placed.sandboxd_key,
    )


def initialize_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    placed: PlacedVm,
    *,
    tenant_id: str,
    env: dict[str, str],
    session_ids: list[str],
) -> DaemonInitResult:
    """Run after every boot or restore: CloseConnections, then daemon Init.

    Raises SandboxVmUnusableError (after stopping the VM) when the daemon has
    no key or another key, SandboxDaemonError and HostAgentError otherwise.
    """
    vm = placed.vm
    client_factory.client(placed.node.address).close_connections(
        sandbox_id=vm.sandbox_id, attempt=vm.attempt, generation=vm.generation
    )
    try:
        return sandbox_daemon(client_factory, placed).init(
            generation=vm.generation,
            scratch_gib=vm.scratch_gib,
            env=env,
            session_ids=session_ids,
        )
    except SandboxDaemonError as e:
        if not e.vm_unusable:
            raise
        sandbox_id = UUID(vm.sandbox_id)
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=True):
            discard_unusable_vm(
                shared_cache,
                tenant_cache,
                client_factory,
                tenant_id=tenant_id,
                node=placed.node,
                vm=vm,
                why=e.reason.value,
            )
        raise SandboxVmUnusableError(sandbox_id, vm.attempt + 1, e.reason.value) from e


def touch_sandbox_vm(tenant_cache: CacheBackend, placed: PlacedVm) -> bool:
    """Record activity of a placed VM. False when the record names another
    VM instance (the sandbox was replaced)."""
    return touch_sandbox_placement(
        tenant_cache,
        UUID(placed.vm.sandbox_id),
        node_id=placed.node.node_id,
        attempt=placed.vm.attempt,
        generation=placed.vm.generation,
        now=int(time.time()),
    )


def _live_instance(
    client_factory: HostAgentClientFactory,
    address: str,
    sandbox_id: UUID,
    generation: int,
) -> AgentVm | None:
    vm = find_vm(client_factory.client(address).list_vms(), sandbox_id, generation)
    return vm if vm is not None and vm.state.is_live() else None


def stop_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    checkpointer: SandboxCheckpointer,
    *,
    tenant_id: str,
    sandbox_id: UUID,
) -> VmStopOutcome:
    """Stop the placed VM after a saved checkpoint and a fresh liveness check."""
    with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
        if lock is None:
            return VmStopOutcome.LOCKED
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None:
            return VmStopOutcome.NOT_PLACED
        node = get_registered_node(shared_cache, placement.node_id)
        if node is None:
            return VmStopOutcome.NODE_UNREACHABLE

        def gone() -> VmStopOutcome:
            forget_placement(
                shared_cache,
                tenant_cache,
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                node_id=placement.node_id,
                attempt=placement.attempt,
                generation=placement.generation,
            )
            return VmStopOutcome.ALREADY_GONE

        try:
            vm = _live_instance(
                client_factory, node.address, sandbox_id, placement.generation
            )
            if vm is None:
                return gone()
            if not checkpointer.save_checkpoint(
                tenant_id=tenant_id, sandbox_id=sandbox_id, vm=vm
            ):
                return VmStopOutcome.KEPT_NO_CHECKPOINT
            # The checkpoint can take a while: check liveness again.
            lock.extend(60)
            vm = _live_instance(
                client_factory, node.address, sandbox_id, placement.generation
            )
            if vm is None:
                return gone()
            client_factory.client(node.address).stop(
                sandbox_id=str(sandbox_id),
                attempt=vm.attempt,
                generation=vm.generation,
            )
        except HostAgentError as e:
            if e.reason is HostAgentErrorReason.SANDBOX_NOT_FOUND:
                return gone()
            if e.reason is None:
                return VmStopOutcome.NODE_UNREACHABLE
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
            "sandbox_fc_stopped node=%s sandbox=%s attempt=%d generation=%d",
            placement.node_id,
            sandbox_id,
            placement.attempt,
            placement.generation,
        )
        return VmStopOutcome.STOPPED


def is_vm_idle(last_active: int, now: int) -> bool:
    """P4: no activity in the record for the idle timeout."""
    return now - last_active >= SANDBOX_FC_IDLE_TIMEOUT_SECONDS


def evict_idle_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    checkpointer: SandboxCheckpointer,
    activity: SandboxActivityProbe,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    last_active: int,
    now: int,
) -> VmStopOutcome:
    """The idle evictor: stop a VM idle past the timeout (P4) when nothing
    runs in it (P7). Without checkpoint support it decides and keeps the VM."""
    if not is_vm_idle(last_active, now):
        return VmStopOutcome.NOT_IDLE
    if not checkpointer.supported:
        return VmStopOutcome.KEPT_NO_CHECKPOINT
    if activity.is_busy(tenant_id=tenant_id, sandbox_id=sandbox_id):
        return VmStopOutcome.KEPT_BUSY
    return stop_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        checkpointer,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )
