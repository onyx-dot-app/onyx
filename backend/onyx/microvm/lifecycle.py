"""Firecracker sandbox VM lifecycle (ENG-4576): wake, heartbeat, stop, idle sleep.

- Wake (P5): `wake_sandbox_vm` is the only entry that starts a VM. Call it from
  the first tool call that needs the sandbox; nothing pre-warms.
- Heartbeat: `refresh_sandbox_placement` refreshes the placement record TTL.
  The reconcile loop also refreshes every record that matches a live VM.
- Stop: never without a saved checkpoint, and the VM's liveness is checked
  again right before the Stop call.
- Idle sleep: after `SANDBOX_FC_IDLE_TIMEOUT_SECONDS` without a heartbeat (P4),
  and only when nothing runs in the sandbox (P7).

Until session saves (ENG-4580) and the daemon's execution report (ENG-4575)
exist, the defaults (`NoCheckpointSupport`, `UnknownActivity`) keep every VM.
"""

import abc
import random
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from onyx.cache.interface import CacheBackend
from onyx.microvm.agent_client import (
    AgentVm,
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
)
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.placement import (
    PlacedVm,
    VmRequest,
    find_vm,
    forget_placement,
    place_sandbox_vm,
    record_placement,
    sandbox_placement_lock,
)
from onyx.microvm.registry import (
    SandboxPlacement,
    get_registered_node,
    get_sandbox_placement,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SandboxCheckpointer(abc.ABC):
    """Saves the session state of a VM before the VM may be stopped."""

    @abc.abstractmethod
    def save_checkpoint(self, *, tenant_id: str, sandbox_id: UUID, vm: AgentVm) -> bool:
        """True only when the VM's state is saved and committed."""
        raise NotImplementedError


class NoCheckpointSupport(SandboxCheckpointer):
    """No session saves yet (ENG-4580): no VM is ever stopped automatically."""

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


def refresh_sandbox_placement(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    placement: SandboxPlacement,
) -> bool:
    """Heartbeat: refresh the record if it still names this VM instance."""
    if get_sandbox_placement(tenant_cache, sandbox_id) != placement:
        return False
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        placement=placement,
    )
    return True


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
        )
        logger.info(
            "sandbox_fc_stopped node=%s sandbox=%s generation=%d",
            placement.node_id,
            sandbox_id,
            placement.generation,
        )
        return VmStopOutcome.STOPPED


def is_vm_idle(
    last_heartbeat: datetime | None, created_at: datetime, now: datetime
) -> bool:
    """P4: no heartbeat for the idle timeout (no heartbeat yet: since creation)."""
    reference = last_heartbeat or created_at
    return reference < now - timedelta(seconds=SANDBOX_FC_IDLE_TIMEOUT_SECONDS)


def sleep_idle_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    checkpointer: SandboxCheckpointer,
    activity: SandboxActivityProbe,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    last_heartbeat: datetime | None,
    created_at: datetime,
    now: datetime,
) -> VmStopOutcome:
    """Stop an idle VM (P4) when nothing runs in it (P7)."""
    if not is_vm_idle(last_heartbeat, created_at, now):
        return VmStopOutcome.NOT_IDLE
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
