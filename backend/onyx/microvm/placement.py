"""Placement and admission of Firecracker sandbox VMs (ENG-4577).

Admission (D7): one VM per sandbox, and a sandbox is one per user; per node,
the agent admits on memory, disk and VM slots. There is no per-tenant cap.

Placement samples K registered nodes, ranks them by free memory from
`NodeInfo`, and calls `Create` on the best one. A node that refuses for a
node-local reason (capacity, template) moves placement to the next node; when
no node accepts, `SANDBOX_CAPACITY_UNAVAILABLE` carries the reasons.

Guest daemon key: each attempt gets a random key, stored (encrypted) before
`Create` sends it, so a repeat `Create` of the same attempt sends the same key.
When the daemon rejects the key, the key is lost, or the VM exited, the VM is
unusable: placement stops it and creates the next attempt. The caller must
then store `PlacedVm.vm.attempt` as the sandbox's attempt.

Pending Create: before `Create`, placement pins the sandbox to the node. Until
the Create outcome is known (success, or a node-local refusal), later
placements try only that node, because a Create that timed out can still
start the VM there.
"""

import random
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
    SANDBOX_FC_PLACEMENT_TTL_SECONDS,
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
    clear_sandbox_daemon_key,
    clear_sandbox_placement,
    get_registered_node,
    get_sandbox_daemon_key,
    get_sandbox_placement,
    index_sandbox_placement,
    list_registered_nodes,
    refresh_sandbox_daemon_key,
    renew_sandbox_placement,
    set_sandbox_daemon_key,
    set_sandbox_placement,
    unindex_sandbox_placement,
)
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PLACEMENT_LOCK_PREFIX = "sandbox_fc:place_lock:"
_PENDING_CREATE_PREFIX = "sandbox_fc:pending_create:"
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
    """Serializes placement, stop and reconcile of one sandbox.

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
) -> None:
    """Write (or refresh) the placement record and the node's index entry."""
    set_sandbox_placement(
        tenant_cache, sandbox_id, placement, SANDBOX_FC_PLACEMENT_TTL_SECONDS
    )
    refresh_sandbox_daemon_key(
        tenant_cache, sandbox_id, SANDBOX_FC_PLACEMENT_TTL_SECONDS
    )
    index_sandbox_placement(
        shared_cache,
        node_id=placement.node_id,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )


def refresh_placement(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    placement: SandboxPlacement,
) -> bool:
    """Refresh the record only while it still names `placement`. The check and
    the TTL reset are one atomic step, so a stale caller cannot overwrite a
    replacement VM's record."""
    if not renew_sandbox_placement(
        tenant_cache, sandbox_id, placement, SANDBOX_FC_PLACEMENT_TTL_SECONDS
    ):
        return False
    refresh_sandbox_daemon_key(
        tenant_cache, sandbox_id, SANDBOX_FC_PLACEMENT_TTL_SECONDS
    )
    index_sandbox_placement(
        shared_cache,
        node_id=placement.node_id,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )
    return True


def _pin_pending_create(
    tenant_cache: CacheBackend, sandbox_id: UUID, node_id: str
) -> None:
    tenant_cache.set(
        _PENDING_CREATE_PREFIX + str(sandbox_id),
        node_id,
        ex=SANDBOX_FC_PLACEMENT_TTL_SECONDS,
    )


def _pending_create_node(tenant_cache: CacheBackend, sandbox_id: UUID) -> str | None:
    raw = tenant_cache.get(_PENDING_CREATE_PREFIX + str(sandbox_id))
    return raw.decode() if raw is not None else None


def clear_pending_create(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    tenant_cache.delete(_PENDING_CREATE_PREFIX + str(sandbox_id))


def forget_placement(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    node_id: str,
) -> None:
    clear_sandbox_placement(tenant_cache, sandbox_id)
    clear_sandbox_daemon_key(tenant_cache, sandbox_id)
    unindex_sandbox_placement(
        shared_cache, node_id=node_id, tenant_id=tenant_id, sandbox_id=sandbox_id
    )


def find_vm(vms: list[AgentVm], sandbox_id: UUID, generation: int) -> AgentVm | None:
    key = str(sandbox_id)
    return next(
        (vm for vm in vms if vm.sandbox_id == key and vm.generation == generation),
        None,
    )


def _existing_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
) -> tuple[_LiveVm | None, VmRequest]:
    """The live VM that the placement record names, or None after clearing a
    record whose VM is gone. Raises when the sandbox has a live VM of another
    attempt (one VM per sandbox).

    The returned request has the next attempt when the record's VM exited: the
    agent keeps an exited VM and returns it for a repeat Create of its attempt.
    """
    placement = get_sandbox_placement(tenant_cache, request.sandbox_id)
    if placement is None:
        return None, request
    node = get_registered_node(shared_cache, placement.node_id)
    if node is None:
        # The node stopped registering. Its VM may still run, so do not start
        # a second one; the record expires with its TTL.
        raise capacity_unavailable_error(
            [
                NodeRefusal(
                    node_id=placement.node_id,
                    reason=REASON_NODE_UNREACHABLE,
                    detail="the node of the current placement is not registered",
                )
            ]
        )
    try:
        vms = client_factory.client(node.address).list_vms()
    except HostAgentError as e:
        raise capacity_unavailable_error(
            [
                NodeRefusal(
                    node_id=node.node_id,
                    reason=e.reason.value if e.reason else REASON_NODE_UNREACHABLE,
                    detail=e.message,
                )
            ]
        ) from e
    vm = find_vm(vms, request.sandbox_id, placement.generation)
    if vm is not None and not vm.state.is_live() and vm.attempt >= request.attempt:
        discard_unusable_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            tenant_id=request.tenant_id,
            node=node,
            vm=vm,
            why=_REASON_VM_EXITED,
        )
        return None, request.model_copy(update={"attempt": vm.attempt + 1})
    if vm is None or not vm.state.is_live():
        forget_placement(
            shared_cache,
            tenant_cache,
            tenant_id=request.tenant_id,
            sandbox_id=request.sandbox_id,
            node_id=placement.node_id,
        )
        return None, request
    if vm.attempt != request.attempt:
        raise _conflict_error(request.sandbox_id, node.node_id, "ATTEMPT_CONFLICT")
    return _LiveVm(node=node, vm=vm), request


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
            refusals.append(
                NodeRefusal(
                    node_id=node.node_id,
                    reason=e.reason.value if e.reason else REASON_NODE_UNREACHABLE,
                    detail=e.message,
                )
            )
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
    refusals: list[NodeRefusal],
) -> PlacedVm | None:
    """Create on `node`. None when the node refused for a node-local reason
    (added to `refusals`); then no VM of this Create runs there."""
    lock.extend(_LOCK_LEASE_SECONDS)
    _pin_pending_create(tenant_cache, request.sandbox_id, node.node_id)
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
            # The VM may exist there. The pending-Create pin keeps the next
            # placement on this node.
            raise capacity_unavailable_error(
                [
                    *refusals,
                    NodeRefusal(
                        node_id=node.node_id,
                        reason=REASON_NODE_UNREACHABLE,
                        detail=e.message,
                    ),
                ]
            ) from e
        if e.reason in (
            HostAgentErrorReason.ATTEMPT_CONFLICT,
            HostAgentErrorReason.STALE_ATTEMPT,
            HostAgentErrorReason.SANDBOX_IN_DOUBT,
        ):
            # The node holds state for this sandbox: never place it on a
            # second node.
            raise _conflict_error(
                request.sandbox_id, node.node_id, e.reason.value
            ) from e
        if e.reason not in _NEXT_NODE_REASONS:
            # Not a known refusal: keep the pin, the outcome is unknown.
            raise capacity_unavailable_error(
                [
                    *refusals,
                    NodeRefusal(
                        node_id=node.node_id, reason=e.reason.value, detail=e.message
                    ),
                ]
            ) from e
        clear_pending_create(tenant_cache, request.sandbox_id)
        logger.info(
            "sandbox_fc_node_refused node=%s sandbox=%s reason=%s",
            node.node_id,
            request.sandbox_id,
            e.reason.value,
        )
        refusals.append(
            NodeRefusal(node_id=node.node_id, reason=e.reason.value, detail=e.message)
        )
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
) -> PlacedVm:
    refusals: list[NodeRefusal] = []
    if pinned is not None:
        # An earlier Create on this node has no known outcome: its VM may run
        # there, so try that node first and skip the free-memory ranking.
        lock.extend(_LOCK_LEASE_SECONDS + SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS)
        infos = _node_infos(client_factory, [pinned], refusals)
        if not infos:
            raise capacity_unavailable_error(refusals)
        node, info = infos[0]
        if info.template(request.template) is None:
            clear_pending_create(tenant_cache, request.sandbox_id)
            refusals.append(
                NodeRefusal(
                    node_id=node.node_id,
                    reason=HostAgentErrorReason.TEMPLATE_MISSING.value,
                    detail=f"template {request.template} is not on the node",
                )
            )
        else:
            placed = _try_node(
                tenant_cache, client_factory, request, node, info, key, lock, refusals
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
                tenant_cache, client_factory, request, node, info, key, lock, refusals
            )
            if placed is not None:
                return placed
    raise capacity_unavailable_error(refusals)


def _key_for_attempt(tenant_cache: CacheBackend, request: VmRequest) -> SecretStr:
    """The attempt's stored key, or a new one, stored before Create sends it."""
    key = get_sandbox_daemon_key(
        tenant_cache, request.sandbox_id, attempt=request.attempt
    )
    if key is None:
        key = new_sandboxd_key()
        set_sandbox_daemon_key(
            tenant_cache,
            request.sandbox_id,
            attempt=request.attempt,
            key=key,
            ttl_seconds=SANDBOX_FC_PLACEMENT_TTL_SECONDS,
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
    """Stop a VM whose guest daemon does not accept its key, and clear its
    records. No checkpoint: nothing can read the VM. Raises
    SANDBOX_CAPACITY_UNAVAILABLE when the node does not answer."""
    sandbox_id = UUID(vm.sandbox_id)
    try:
        client_factory.client(node.address).stop(
            sandbox_id=vm.sandbox_id, attempt=vm.attempt, generation=vm.generation
        )
    except HostAgentError as e:
        if e.reason is not HostAgentErrorReason.SANDBOX_NOT_FOUND:
            raise capacity_unavailable_error(
                [
                    NodeRefusal(
                        node_id=node.node_id,
                        reason=e.reason.value if e.reason else REASON_NODE_UNREACHABLE,
                        detail=e.message,
                    )
                ]
            ) from e
    current = get_sandbox_placement(tenant_cache, sandbox_id)
    if current is None or current == SandboxPlacement(
        node_id=node.node_id, generation=vm.generation
    ):
        forget_placement(
            shared_cache,
            tenant_cache,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            node_id=node.node_id,
        )
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
                [
                    NodeRefusal(
                        node_id=unusable.node.node_id,
                        reason=e.reason.value if e.reason else REASON_NODE_UNREACHABLE,
                        detail=e.message,
                    )
                ]
            ) from e
        key = str(request.sandbox_id)
        vm = next(
            (v for v in vms if v.sandbox_id == key and v.attempt == request.attempt),
            None,
        )
    if vm is None:
        clear_sandbox_daemon_key(tenant_cache, request.sandbox_id)
    else:
        discard_unusable_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            tenant_id=request.tenant_id,
            node=unusable.node,
            vm=vm,
            why=unusable.reason,
        )
    clear_pending_create(tenant_cache, request.sandbox_id)


def _pinned_node(
    shared_cache: CacheBackend, tenant_cache: CacheBackend, sandbox_id: UUID
) -> RegisteredNode | None:
    node_id = _pending_create_node(tenant_cache, sandbox_id)
    if node_id is None:
        return None
    node = get_registered_node(shared_cache, node_id)
    if node is None:
        # The VM of the unfinished Create may still run there; the pin
        # expires with its TTL.
        raise capacity_unavailable_error(
            [
                NodeRefusal(
                    node_id=node_id,
                    reason=REASON_NODE_UNREACHABLE,
                    detail="the node of an unfinished Create is not registered",
                )
            ]
        )
    return node


def place_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    rng: random.Random | None = None,
) -> PlacedVm:
    """Return the sandbox's live VM, or start one and write its placement record.

    `PlacedVm.vm.attempt` is larger than `request.attempt` when the VM of
    `request.attempt` was unusable and placement created the next attempt.

    Raises OnyxError SANDBOX_CAPACITY_UNAVAILABLE (no node accepts) or CONFLICT
    (a VM of another attempt holds the sandbox), and
    SandboxProvisionContentionError when another placement holds the lock.
    """
    with sandbox_placement_lock(
        tenant_cache, request.sandbox_id, blocking=True
    ) as lock:
        if lock is None:
            raise SandboxProvisionContentionError(str(request.sandbox_id))
        existing, request = _existing_vm(
            shared_cache, tenant_cache, client_factory, request
        )
        if existing is not None:
            key = get_sandbox_daemon_key(
                tenant_cache, request.sandbox_id, attempt=existing.vm.attempt
            )
            if key is not None:
                record_placement(
                    shared_cache,
                    tenant_cache,
                    tenant_id=request.tenant_id,
                    sandbox_id=request.sandbox_id,
                    placement=SandboxPlacement(
                        node_id=existing.node.node_id,
                        generation=existing.vm.generation,
                    ),
                )
                return PlacedVm(
                    node=existing.node,
                    vm=existing.vm,
                    created=False,
                    sandboxd_key=key,
                )
            discard_unusable_vm(
                shared_cache,
                tenant_cache,
                client_factory,
                tenant_id=request.tenant_id,
                node=existing.node,
                vm=existing.vm,
                why="key_lost",
            )
            request = request.model_copy(update={"attempt": request.attempt + 1})

        refusals: list[NodeRefusal] = []
        for _ in range(_MAX_ATTEMPTS):
            key = _key_for_attempt(tenant_cache, request)
            pinned = _pinned_node(shared_cache, tenant_cache, request.sandbox_id)
            nodes = list_registered_nodes(shared_cache)
            try:
                placed = _place_new(
                    tenant_cache,
                    client_factory,
                    request,
                    nodes,
                    pinned,
                    lock,
                    rng or random.Random(),
                    key,
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
                continue
            record_placement(
                shared_cache,
                tenant_cache,
                tenant_id=request.tenant_id,
                sandbox_id=request.sandbox_id,
                placement=SandboxPlacement(
                    node_id=placed.node.node_id, generation=placed.vm.generation
                ),
            )
            clear_pending_create(tenant_cache, request.sandbox_id)
            logger.info(
                "sandbox_fc_placed node=%s sandbox=%s attempt=%d generation=%d created=%s",
                placed.node.node_id,
                request.sandbox_id,
                request.attempt,
                placed.vm.generation,
                placed.created,
            )
            return placed
        raise capacity_unavailable_error(refusals)
