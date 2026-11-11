"""Placement and admission of Firecracker sandbox VMs (ENG-4577).

Admission (D7): one VM per sandbox, and a sandbox is one per user; per node,
the agent admits on memory, disk and VM slots. There is no per-tenant cap.

Placement samples K registered nodes, ranks them by free memory from
`NodeInfo`, and calls `Create` on the best one. A node that refuses for a
node-local reason (capacity, template) moves placement to the next node; when
no node accepts, `SANDBOX_CAPACITY_UNAVAILABLE` carries the reasons.

State model (microvm/README.md, "Sandbox state model"):
- `place_sandbox_vm` is an idempotent ensure. It reads the durable placement
  record and asks that node's agent (`List`) whether the VM runs. A running
  VM is returned; otherwise placement replaces it with the next attempt. It
  never waits for a node report.
- One VM per sandbox: before `Create`, placement takes the sandbox's
  reservation atomically (SET NX, or compare-and-set over a leftover one)
  with (attempt, node). A Create with no known outcome keeps the
  reservation, so the next placement repeats the same (attempt, node): the
  agent returns the same VM for a repeat Create. The reservation of a dead
  node is taken over with the next attempt.
- The record write after Create is fenced on (attempt, generation).
- Dead node (no live registration, or no state report within
  `SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS`): its record stays, and placement
  starts the next attempt on a live node. If the old VM reports again, it is an
  orphan with an older attempt, and the report stops it.

Guest daemon key: each attempt gets a random key, stored (encrypted, no TTL)
before `Create` sends it, so a repeat `Create` of the same attempt sends the
same key. When the daemon rejects the key, the key is lost, or the VM exited,
the VM is unusable: placement stops it and creates the next attempt. The
caller must then store `PlacedVm.vm.attempt` as the sandbox's attempt.
"""

import random
import secrets
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr

from onyx.cache.interface import CacheBackend, CacheLock
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.agent_client import (
    GuestKeyRejectedError,
    GuestUnreachableError,
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
    new_sandboxd_key,
)
from onyx.microvm.configs import (
    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
    SANDBOX_FC_CREATE_GUEST_RETRIES,
    SANDBOX_FC_PLACEMENT_CANDIDATES,
)
from onyx.microvm.models import (
    AgentVm,
    NodeInfo,
    NodeRefusal,
    PlacedVm,
    RegisteredNode,
    VmRequest,
)
from onyx.microvm.registry import (
    SandboxPlacement,
    SandboxReservation,
    clear_sandbox_daemon_key,
    clear_sandbox_placement_if,
    get_live_node,
    get_sandbox_daemon_key,
    get_sandbox_placement,
    get_sandbox_reservation,
    index_sandbox_placement,
    list_live_nodes,
    release_sandbox_reservation,
    reserve_sandbox,
    set_sandbox_daemon_key,
    touch_sandbox_placement,
    unindex_sandbox_placement,
    write_sandbox_placement,
)
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PLACEMENT_LOCK_PREFIX = "sandbox_fc:place_lock:"
_LOCK_WAIT_SECONDS = SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS + 15
_LOCK_LEASE_SECONDS = SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS + 30

# Capacity reasons that are not agent ErrorReasons.
REASON_NO_NODES = "NO_NODES"
REASON_NODE_UNREACHABLE = "NODE_UNREACHABLE"
# Create returned a VM that is not running (the agent keeps exited VMs).
_REASON_VM_EXITED = "VM_EXITED"

# Create failed for a node-local reason: another node may accept.
_NEXT_NODE_REASONS: frozenset[HostAgentErrorReason] = frozenset(
    {
        HostAgentErrorReason.TEMPLATE_MISSING,
        HostAgentErrorReason.TEMPLATE_INCOMPATIBLE,
        HostAgentErrorReason.TEMPLATE_SHAPE_MISMATCH,
        HostAgentErrorReason.SCRATCH_TOO_LARGE,
        HostAgentErrorReason.CAPACITY_MEMORY,
        HostAgentErrorReason.CAPACITY_DISK,
        HostAgentErrorReason.CAPACITY_VM_SLOTS,
        HostAgentErrorReason.VMM_FAILED,
        HostAgentErrorReason.NODE_DRAINING,
        # The VM stopped or exited during Create.
        HostAgentErrorReason.VM_NOT_RUNNING,
    }
)
# Attempts per placement call: the first, and one after an unusable VM.
_MAX_ATTEMPTS = 2


class _LiveVm(BaseModel):
    model_config = ConfigDict(frozen=True)

    node: RegisteredNode
    vm: AgentVm


class _Unusable(Exception):
    """Create on `node` gave a VM that nothing can use. `vm` is None when
    Create did not return it (GUEST_KEY_REJECTED)."""

    def __init__(
        self, node: RegisteredNode, reason: str, detail: str, vm: AgentVm | None
    ) -> None:
        super().__init__(detail)
        self.node = node
        self.reason = reason
        self.detail = detail
        self.vm = vm


def capacity_unavailable_error(refusals: list[NodeRefusal]) -> OnyxError:
    """`SANDBOX_CAPACITY_UNAVAILABLE` with the most common reason in `extra`."""
    if not refusals:
        return OnyxError(
            OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE,
            "No Firecracker node is registered",
            extra={"reason": REASON_NO_NODES, "nodes": {}},
        )
    reason = Counter(r.reason for r in refusals).most_common(1)[0][0]
    summary = ", ".join(f"{r.node_id}: {r.reason}" for r in refusals)
    return OnyxError(
        OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE,
        f"No Firecracker node can start the sandbox ({summary})",
        extra={"reason": reason, "nodes": {r.node_id: r.reason for r in refusals}},
    )


def _refusal(node_id: str, e: HostAgentError) -> NodeRefusal:
    return NodeRefusal(
        node_id=node_id,
        reason=e.reason.value if e.reason else REASON_NODE_UNREACHABLE,
        detail=e.message,
    )


def _conflict_error(sandbox_id: UUID, node_id: str, reason: str) -> OnyxError:
    return OnyxError(
        OnyxErrorCode.CONFLICT,
        f"Sandbox {sandbox_id} already has a VM on node {node_id} ({reason})",
        extra={"reason": reason, "node": node_id},
    )


@contextmanager
def sandbox_placement_lock(
    tenant_cache: CacheBackend, sandbox_id: UUID, *, blocking: bool
) -> Iterator[CacheLock | None]:
    """Serializes placement, stop and reconcile of one sandbox, so a second
    caller waits instead of failing on the reservation.

    Yields None when `blocking` is False and another holder has the lock.
    """
    lock = tenant_cache.lock(
        _PLACEMENT_LOCK_PREFIX + str(sandbox_id), timeout=_LOCK_LEASE_SECONDS
    )
    acquired = (
        lock.acquire(blocking_timeout=_LOCK_WAIT_SECONDS)
        if blocking
        else lock.acquire(blocking=False)
    )
    if not acquired:
        if blocking:
            raise SandboxProvisionContentionError(
                f"Sandbox {sandbox_id} placement is in progress elsewhere"
            )
        yield None
        return
    try:
        yield lock
    finally:
        if lock.owned():
            lock.release()


def record_placement(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    placement: SandboxPlacement,
) -> bool:
    """Write the durable record (fenced on attempt and generation) and the
    node's index entry. False when a newer record exists."""
    if not write_sandbox_placement(tenant_cache, sandbox_id, placement):
        return False
    index_sandbox_placement(
        shared_cache,
        node_id=placement.node_id,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )
    return True


def forget_placement(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    node_id: str,
    attempt: int,
    generation: int,
) -> bool:
    """Clear the record, the daemon key and the index entry of one VM
    instance. Nothing changes when the record names another instance."""
    if not clear_sandbox_placement_if(
        tenant_cache,
        sandbox_id,
        node_id=node_id,
        attempt=attempt,
        generation=generation,
    ):
        return False
    clear_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=attempt)
    unindex_sandbox_placement(
        shared_cache, node_id=node_id, tenant_id=tenant_id, sandbox_id=sandbox_id
    )
    return True


def find_vm(vms: list[AgentVm], sandbox_id: UUID, generation: int) -> AgentVm | None:
    key = str(sandbox_id)
    return next(
        (vm for vm in vms if vm.sandbox_id == key and vm.generation == generation),
        None,
    )


class _Reservation:
    """The reservation this placement holds, and its stored value."""

    def __init__(self, sandbox_id: UUID, current: SandboxReservation, raw: bytes):
        self.sandbox_id = sandbox_id
        self.current = current
        self.raw = raw

    def move(
        self,
        tenant_cache: CacheBackend,
        *,
        node_id: str | None = None,
        attempt: int | None = None,
    ) -> None:
        """Compare-and-set to a new node or attempt. Raises
        SandboxProvisionContentionError when another caller changed it."""
        new = self.current.model_copy(
            update={
                "node_id": self.current.node_id if node_id is None else node_id,
                "attempt": self.current.attempt if attempt is None else attempt,
            }
        )
        if new == self.current:
            return
        raw = reserve_sandbox(tenant_cache, self.sandbox_id, new, replaces=self.raw)
        if raw is None:
            raise SandboxProvisionContentionError(
                f"Sandbox {self.sandbox_id} reservation changed during placement"
            )
        self.current, self.raw = new, raw

    def release(self, tenant_cache: CacheBackend) -> None:
        if not release_sandbox_reservation(tenant_cache, self.sandbox_id, self.raw):
            logger.warning(
                "sandbox_fc_reservation_changed sandbox=%s attempt=%d",
                self.sandbox_id,
                self.current.attempt,
            )


def _take_reservation(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    attempt: int,
) -> tuple[_Reservation, RegisteredNode | None]:
    """Take the sandbox's reservation for `attempt` or later, atomically.

    A leftover reservation (a Create with no known outcome, or a crash) on a
    live node is resumed with its attempt and node: a repeat Create returns
    the same VM. On a dead node, or for an older attempt, it is taken over
    with the next attempt. Returns the reservation and the node to try first.
    """
    owner = secrets.token_hex(8)
    found = get_sandbox_reservation(tenant_cache, sandbox_id)
    pinned: RegisteredNode | None = None
    if found is None:
        new = SandboxReservation(attempt=attempt, node_id="", owner=owner)
        raw = reserve_sandbox(tenant_cache, sandbox_id, new, replaces=None)
    else:
        left, left_raw = found
        node = (
            get_live_node(shared_cache, left.node_id, int(time.time()))
            if left.node_id
            else None
        )
        if left.attempt >= attempt and (not left.node_id or node is not None):
            pinned = node
            new = SandboxReservation(
                attempt=left.attempt, node_id=left.node_id, owner=owner
            )
        else:
            if left.node_id and node is None:
                logger.warning(
                    "sandbox_fc_reservation_node_dead sandbox=%s node=%s attempt=%d",
                    sandbox_id,
                    left.node_id,
                    left.attempt,
                )
            new = SandboxReservation(
                attempt=max(attempt, left.attempt + 1), node_id="", owner=owner
            )
        raw = reserve_sandbox(tenant_cache, sandbox_id, new, replaces=left_raw)
    if raw is None:
        raise SandboxProvisionContentionError(
            f"Sandbox {sandbox_id} is reserved by another placement"
        )
    return _Reservation(sandbox_id, new, raw), pinned


def _ensure_existing(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
) -> tuple[PlacedVm | None, int]:
    """Check the durable record against its node's agent.

    Returns the running VM, or None and the lowest attempt for a new VM.
    Raises when the record's node is registered but does not answer, or when
    the running VM's attempt is older than `request.attempt`.
    """
    record = get_sandbox_placement(tenant_cache, request.sandbox_id)
    if record is None:
        return None, request.attempt
    next_attempt = max(request.attempt, record.attempt + 1)
    node = get_live_node(shared_cache, record.node_id, int(time.time()))
    if node is None:
        # Dead node: start the next attempt elsewhere. The fenced record
        # write replaces this record; a VM that reports again is an orphan.
        logger.warning(
            "sandbox_fc_record_node_dead sandbox=%s node=%s attempt=%d",
            request.sandbox_id,
            record.node_id,
            record.attempt,
        )
        unindex_sandbox_placement(
            shared_cache,
            node_id=record.node_id,
            tenant_id=request.tenant_id,
            sandbox_id=request.sandbox_id,
        )
        return None, next_attempt
    try:
        vms = client_factory.client(node.address).list_vms()
    except HostAgentError as e:
        # A registered node that does not answer may still run the VM.
        raise capacity_unavailable_error([_refusal(node.node_id, e)]) from e
    vm = find_vm(vms, request.sandbox_id, record.generation)
    if vm is None or vm.attempt != record.attempt:
        forget_placement(
            shared_cache,
            tenant_cache,
            tenant_id=request.tenant_id,
            sandbox_id=request.sandbox_id,
            node_id=record.node_id,
            attempt=record.attempt,
            generation=record.generation,
        )
        return None, next_attempt
    if not vm.state.is_live():
        discard_unusable_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            tenant_id=request.tenant_id,
            node=node,
            vm=vm,
            why=_REASON_VM_EXITED,
        )
        return None, next_attempt
    if vm.attempt < request.attempt:
        raise _conflict_error(request.sandbox_id, node.node_id, "ATTEMPT_CONFLICT")
    key = get_sandbox_daemon_key(tenant_cache, request.sandbox_id, attempt=vm.attempt)
    if key is None:
        discard_unusable_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            tenant_id=request.tenant_id,
            node=node,
            vm=vm,
            why="key_lost",
        )
        return None, next_attempt
    touch_sandbox_placement(
        tenant_cache,
        request.sandbox_id,
        node_id=node.node_id,
        attempt=vm.attempt,
        generation=vm.generation,
        now=int(time.time()),
    )
    return PlacedVm(node=node, vm=vm, created=False, sandboxd_key=key), next_attempt


def _node_infos(
    client_factory: HostAgentClientFactory,
    nodes: list[RegisteredNode],
    refusals: list[NodeRefusal],
) -> list[tuple[RegisteredNode, NodeInfo]]:
    infos: list[tuple[RegisteredNode, NodeInfo]] = []
    for node in nodes:
        try:
            infos.append((node, client_factory.client(node.address).node_info()))
        except HostAgentError as e:
            refusals.append(_refusal(node.node_id, e))
    return infos


def _rank(
    request: VmRequest,
    infos: list[tuple[RegisteredNode, NodeInfo]],
    refusals: list[NodeRefusal],
) -> list[tuple[RegisteredNode, NodeInfo]]:
    """Nodes that can hold the VM, most free memory first."""
    eligible: list[tuple[RegisteredNode, NodeInfo]] = []
    for node, info in infos:
        template = info.template(request.template)
        if template is None:
            refusals.append(
                NodeRefusal(
                    node_id=node.node_id,
                    reason=HostAgentErrorReason.TEMPLATE_MISSING.value,
                    detail=f"template {request.template} is not on the node",
                )
            )
        elif info.mem_available_mib < template.mem_mib:
            refusals.append(
                NodeRefusal(
                    node_id=node.node_id,
                    reason=HostAgentErrorReason.CAPACITY_MEMORY.value,
                    detail=(
                        f"{info.mem_available_mib} MiB free, "
                        f"the VM needs {template.mem_mib} MiB"
                    ),
                )
            )
        else:
            eligible.append((node, info))
    return sorted(eligible, key=lambda pair: pair[1].mem_available_mib, reverse=True)


def _create_on(
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    node: RegisteredNode,
    info: NodeInfo,
    key: SecretStr,
    lock: CacheLock,
) -> PlacedVm:
    """Create on one node. The daemon did not take the key in time: the VM
    runs, so retry the same attempt with the same key. Raises _Unusable when
    the VM is not running or the daemon rejects the key."""
    template = info.template(request.template)
    if template is None:
        raise ValueError(f"template {request.template} is not on {node.node_id}")
    client = client_factory.client(node.address)
    for retry in range(SANDBOX_FC_CREATE_GUEST_RETRIES + 1):
        try:
            result = client.create(
                sandbox_id=str(request.sandbox_id),
                attempt=request.attempt,
                template=template.version,
                vcpus=template.vcpus,
                mem_mib=template.mem_mib,
                scratch_gib=max(request.scratch_gib or 0, template.scratch_gib),
                tenant_id=request.tenant_id,
                sandboxd_key=key,
            )
        except GuestKeyRejectedError as e:
            raise _Unusable(
                node, HostAgentErrorReason.GUEST_KEY_REJECTED.value, e.message, None
            ) from e
        except GuestUnreachableError:
            if retry == SANDBOX_FC_CREATE_GUEST_RETRIES:
                raise
            logger.info(
                "sandbox_fc_create_guest_unreachable node=%s sandbox=%s attempt=%d retry=%d",
                node.node_id,
                request.sandbox_id,
                request.attempt,
                retry + 1,
            )
            lock.extend(_LOCK_LEASE_SECONDS)
            continue
        if not result.vm.state.is_live():
            raise _Unusable(
                node,
                _REASON_VM_EXITED,
                f"Create returned a VM in state {result.vm.state.value}",
                result.vm,
            )
        return PlacedVm(
            node=node, vm=result.vm, created=result.created, sandboxd_key=key
        )
    raise AssertionError("unreachable")


def _try_node(
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    node: RegisteredNode,
    info: NodeInfo,
    key: SecretStr,
    lock: CacheLock,
    reservation: _Reservation,
    refusals: list[NodeRefusal],
) -> PlacedVm | None:
    """Create on `node`. None when the node refused for a node-local reason
    (added to `refusals`); then no VM of this Create runs there. Any outcome
    that may have left a VM there keeps the reservation on this node."""
    lock.extend(_LOCK_LEASE_SECONDS)
    reservation.move(tenant_cache, node_id=node.node_id)
    try:
        return _create_on(client_factory, request, node, info, key, lock)
    except GuestUnreachableError as e:
        # The VM runs on this node: never start a second one elsewhere.
        raise capacity_unavailable_error(
            [
                *refusals,
                NodeRefusal(
                    node_id=node.node_id,
                    reason=HostAgentErrorReason.GUEST_UNREACHABLE.value,
                    detail=e.message,
                ),
            ]
        ) from e
    except HostAgentError as e:
        if e.reason is None:
            # The VM may exist there; the reservation keeps the next
            # placement on this node with this attempt.
            raise capacity_unavailable_error(
                [*refusals, _refusal(node.node_id, e)]
            ) from e
        if e.reason is HostAgentErrorReason.STALE_ATTEMPT:
            # The node already stopped this attempt (an orphan stop, or a
            # Stop after a lost answer): the attempt is used up.
            raise _Unusable(node, e.reason.value, e.message, None) from e
        if e.reason in (
            HostAgentErrorReason.ATTEMPT_CONFLICT,
            HostAgentErrorReason.SANDBOX_IN_DOUBT,
        ):
            # The node holds state for this sandbox: never place it on a
            # second node.
            raise _conflict_error(
                request.sandbox_id, node.node_id, e.reason.value
            ) from e
        if e.reason not in _NEXT_NODE_REASONS:
            # Not a known refusal: the outcome is unknown.
            raise capacity_unavailable_error(
                [*refusals, _refusal(node.node_id, e)]
            ) from e
        logger.info(
            "sandbox_fc_node_refused node=%s sandbox=%s reason=%s",
            node.node_id,
            request.sandbox_id,
            e.reason.value,
        )
        refusals.append(_refusal(node.node_id, e))
        return None


def _place_new(
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    nodes: list[RegisteredNode],
    pinned: RegisteredNode | None,
    lock: CacheLock,
    rng: random.Random,
    key: SecretStr,
    reservation: _Reservation,
    refusals: list[NodeRefusal],
) -> PlacedVm | None:
    """None when every node refused (in `refusals`)."""
    if pinned is not None:
        # The reserved node may run this attempt's VM: try it first and skip
        # the free-memory ranking.
        lock.extend(_LOCK_LEASE_SECONDS + SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS)
        infos = _node_infos(client_factory, [pinned], refusals)
        if not infos:
            raise capacity_unavailable_error(refusals)
        node, info = infos[0]
        if info.template(request.template) is None:
            refusals.append(
                NodeRefusal(
                    node_id=node.node_id,
                    reason=HostAgentErrorReason.TEMPLATE_MISSING.value,
                    detail=f"template {request.template} is not on the node",
                )
            )
        else:
            placed = _try_node(
                tenant_cache,
                client_factory,
                request,
                node,
                info,
                key,
                lock,
                reservation,
                refusals,
            )
            if placed is not None:
                return placed
        nodes = [n for n in nodes if n.node_id != pinned.node_id]
    order = list(nodes)
    rng.shuffle(order)
    for start in range(0, len(order), SANDBOX_FC_PLACEMENT_CANDIDATES):
        batch = order[start : start + SANDBOX_FC_PLACEMENT_CANDIDATES]
        lock.extend(_LOCK_LEASE_SECONDS + SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS)
        for node, info in _rank(
            request, _node_infos(client_factory, batch, refusals), refusals
        ):
            placed = _try_node(
                tenant_cache,
                client_factory,
                request,
                node,
                info,
                key,
                lock,
                reservation,
                refusals,
            )
            if placed is not None:
                return placed
    return None


def _key_for_attempt(tenant_cache: CacheBackend, request: VmRequest) -> SecretStr:
    """The attempt's stored key, or a new one, stored before Create sends it."""
    key = get_sandbox_daemon_key(
        tenant_cache, request.sandbox_id, attempt=request.attempt
    )
    if key is None:
        key = new_sandboxd_key()
        set_sandbox_daemon_key(
            tenant_cache, request.sandbox_id, attempt=request.attempt, key=key
        )
    return key


def discard_unusable_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    *,
    tenant_id: str,
    node: RegisteredNode,
    vm: AgentVm,
    why: str,
) -> None:
    """Stop a VM that nothing can use (no or another daemon key, exited), and
    clear its records. No checkpoint: nothing can read the VM. Raises
    SANDBOX_CAPACITY_UNAVAILABLE when the node does not answer."""
    sandbox_id = UUID(vm.sandbox_id)
    try:
        client_factory.client(node.address).stop(
            sandbox_id=vm.sandbox_id, attempt=vm.attempt, generation=vm.generation
        )
    except HostAgentError as e:
        if e.reason is not HostAgentErrorReason.SANDBOX_NOT_FOUND:
            raise capacity_unavailable_error([_refusal(node.node_id, e)]) from e
    forget_placement(
        shared_cache,
        tenant_cache,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        node_id=node.node_id,
        attempt=vm.attempt,
        generation=vm.generation,
    )
    clear_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt)
    logger.warning(
        "sandbox_fc_vm_discarded node=%s sandbox=%s attempt=%d generation=%d why=%s",
        node.node_id,
        sandbox_id,
        vm.attempt,
        vm.generation,
        why,
    )


def _discard_unusable(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    unusable: _Unusable,
) -> None:
    """Stop the unusable VM of `request.attempt`. Create does not return the
    VM on GUEST_KEY_REJECTED: find it by attempt."""
    vm = unusable.vm
    if vm is None:
        try:
            vms = client_factory.client(unusable.node.address).list_vms()
        except HostAgentError as e:
            raise capacity_unavailable_error(
                [_refusal(unusable.node.node_id, e)]
            ) from e
        key = str(request.sandbox_id)
        vm = next(
            (v for v in vms if v.sandbox_id == key and v.attempt == request.attempt),
            None,
        )
    if vm is None:
        clear_sandbox_daemon_key(
            tenant_cache, request.sandbox_id, attempt=request.attempt
        )
        return
    discard_unusable_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        tenant_id=request.tenant_id,
        node=unusable.node,
        vm=vm,
        why=unusable.reason,
    )


def place_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    rng: random.Random | None = None,
) -> PlacedVm:
    """Ensure the sandbox has one running VM and return it (idempotent).

    `PlacedVm.vm.attempt` can be larger than `request.attempt`: the record's
    VM was gone, exited or unusable, or its node is dead, so placement
    created the next attempt. The caller stores `PlacedVm.vm.attempt`.

    Raises OnyxError SANDBOX_CAPACITY_UNAVAILABLE (no node accepts, or the
    record's node does not answer) or CONFLICT (a node holds another attempt),
    and SandboxProvisionContentionError when another placement holds the lock
    or the reservation.
    """
    with sandbox_placement_lock(
        tenant_cache, request.sandbox_id, blocking=True
    ) as lock:
        if lock is None:
            raise SandboxProvisionContentionError(str(request.sandbox_id))
        existing, attempt = _ensure_existing(
            shared_cache, tenant_cache, client_factory, request
        )
        if existing is not None:
            return existing

        reservation, pinned = _take_reservation(
            shared_cache, tenant_cache, request.sandbox_id, attempt
        )
        # A placement writes its record before it releases its reservation.
        # A record that is new since the check above belongs to a placement
        # that ended meanwhile (only possible after a lock lease expired).
        record = get_sandbox_placement(tenant_cache, request.sandbox_id)
        if record is not None and record.attempt >= attempt:
            reservation.release(tenant_cache)
            existing, _ = _ensure_existing(
                shared_cache, tenant_cache, client_factory, request
            )
            if existing is not None:
                return existing
            raise SandboxProvisionContentionError(
                f"Sandbox {request.sandbox_id} was placed during this placement"
            )
        request = request.model_copy(update={"attempt": reservation.current.attempt})
        refusals: list[NodeRefusal] = []
        for _ in range(_MAX_ATTEMPTS):
            key = _key_for_attempt(tenant_cache, request)
            try:
                placed = _place_new(
                    tenant_cache,
                    client_factory,
                    request,
                    list_live_nodes(shared_cache, int(time.time())),
                    pinned,
                    lock,
                    rng or random.Random(),
                    key,
                    reservation,
                    refusals,
                )
            except _Unusable as unusable:
                refusals.append(
                    NodeRefusal(
                        node_id=unusable.node.node_id,
                        reason=unusable.reason,
                        detail=unusable.detail,
                    )
                )
                _discard_unusable(
                    shared_cache, tenant_cache, client_factory, request, unusable
                )
                request = request.model_copy(update={"attempt": request.attempt + 1})
                reservation.move(tenant_cache, node_id="", attempt=request.attempt)
                pinned = None
                continue
            if placed is None:
                reservation.release(tenant_cache)
                raise capacity_unavailable_error(refusals)
            if not record_placement(
                shared_cache,
                tenant_cache,
                tenant_id=request.tenant_id,
                sandbox_id=request.sandbox_id,
                placement=SandboxPlacement(
                    node_id=placed.node.node_id,
                    attempt=placed.vm.attempt,
                    generation=placed.vm.generation,
                    last_active=int(time.time()),
                ),
            ):
                # A newer record exists: this VM is an orphan with an older
                # attempt, and its node's next report stops it.
                reservation.release(tenant_cache)
                raise _conflict_error(
                    request.sandbox_id, placed.node.node_id, "STALE_ATTEMPT"
                )
            reservation.release(tenant_cache)
            logger.info(
                "sandbox_fc_placed node=%s sandbox=%s attempt=%d generation=%d created=%s",
                placed.node.node_id,
                request.sandbox_id,
                request.attempt,
                placed.vm.generation,
                placed.created,
            )
            return placed
        reservation.release(tenant_cache)
        raise capacity_unavailable_error(refusals)
