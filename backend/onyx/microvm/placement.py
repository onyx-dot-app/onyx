"""Placement and admission of Firecracker sandbox VMs (ENG-4577).

Admission (D7): one VM per sandbox, and a sandbox is one per user; per node,
the agent admits on memory, disk and VM slots. There is no per-tenant cap.

Placement samples K registered nodes, ranks them by free memory from
`NodeInfo`, and calls `Create` on the best one. A node that refuses for a
node-local reason (capacity, template) moves placement to the next node; when
no node accepts, `SANDBOX_CAPACITY_UNAVAILABLE` carries the reasons.
"""

import random
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.cache.interface import CacheBackend, CacheLock
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.agent_client import (
    AgentVm,
    HostAgentClientFactory,
    HostAgentError,
    HostAgentErrorReason,
    NodeInfo,
)
from onyx.microvm.configs import (
    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
    SANDBOX_FC_PLACEMENT_CANDIDATES,
    SANDBOX_FC_PLACEMENT_TTL_SECONDS,
)
from onyx.microvm.registry import (
    RegisteredNode,
    SandboxPlacement,
    clear_sandbox_placement,
    get_registered_node,
    get_sandbox_placement,
    index_sandbox_placement,
    list_registered_nodes,
    set_sandbox_placement,
    unindex_sandbox_placement,
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
    }
)


class VmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    sandbox_id: UUID
    # The sandbox's provisioning attempt number (the existing attempt fence).
    attempt: int
    # Template version; vcpus and mem_mib come from the node's template.
    template: str
    # None = the template's scratch size.
    scratch_gib: int | None = None


class PlacedVm(BaseModel):
    model_config = ConfigDict(frozen=True)

    node: RegisteredNode
    vm: AgentVm
    # False when the VM existed before this call.
    created: bool


class NodeRefusal(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    reason: str
    detail: str


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
    index_sandbox_placement(
        shared_cache,
        node_id=placement.node_id,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
    )


def forget_placement(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    *,
    tenant_id: str,
    sandbox_id: UUID,
    node_id: str,
) -> None:
    clear_sandbox_placement(tenant_cache, sandbox_id)
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
) -> PlacedVm | None:
    """The live VM that the placement record names, or None after clearing a
    record whose VM is gone. Raises when the sandbox has a live VM of another
    attempt (one VM per sandbox)."""
    placement = get_sandbox_placement(tenant_cache, request.sandbox_id)
    if placement is None:
        return None
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
    if vm is None or not vm.state.is_live():
        forget_placement(
            shared_cache,
            tenant_cache,
            tenant_id=request.tenant_id,
            sandbox_id=request.sandbox_id,
            node_id=placement.node_id,
        )
        return None
    if vm.attempt != request.attempt:
        raise _conflict_error(request.sandbox_id, node.node_id, "ATTEMPT_CONFLICT")
    return PlacedVm(node=node, vm=vm, created=False)


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
) -> PlacedVm:
    template = info.template(request.template)
    if template is None:
        raise ValueError(f"template {request.template} is not on {node.node_id}")
    result = client_factory.client(node.address).create(
        sandbox_id=str(request.sandbox_id),
        attempt=request.attempt,
        template=template.version,
        vcpus=template.vcpus,
        mem_mib=template.mem_mib,
        scratch_gib=max(request.scratch_gib or 0, template.scratch_gib),
        tenant_id=request.tenant_id,
    )
    return PlacedVm(node=node, vm=result.vm, created=result.created)


def _place_new(
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    nodes: list[RegisteredNode],
    lock: CacheLock,
    rng: random.Random,
) -> PlacedVm:
    refusals: list[NodeRefusal] = []
    order = list(nodes)
    rng.shuffle(order)
    for start in range(0, len(order), SANDBOX_FC_PLACEMENT_CANDIDATES):
        batch = order[start : start + SANDBOX_FC_PLACEMENT_CANDIDATES]
        lock.extend(_LOCK_LEASE_SECONDS + SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS)
        for node, info in _rank(
            request, _node_infos(client_factory, batch, refusals), refusals
        ):
            lock.extend(_LOCK_LEASE_SECONDS)
            try:
                return _create_on(client_factory, request, node, info)
            except HostAgentError as e:
                if e.reason is None:
                    # The VM may exist there; another node could start a second
                    # one. Reconcile adopts it if it does.
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
                    # The node holds state for this sandbox: never place it
                    # on a second node.
                    raise _conflict_error(
                        request.sandbox_id, node.node_id, e.reason.value
                    ) from e
                if e.reason not in _NEXT_NODE_REASONS:
                    raise
                logger.info(
                    "sandbox_fc_node_refused node=%s sandbox=%s reason=%s",
                    node.node_id,
                    request.sandbox_id,
                    e.reason.value,
                )
                refusals.append(
                    NodeRefusal(
                        node_id=node.node_id, reason=e.reason.value, detail=e.message
                    )
                )
    raise capacity_unavailable_error(refusals)


def place_sandbox_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    request: VmRequest,
    rng: random.Random | None = None,
) -> PlacedVm:
    """Return the sandbox's live VM, or start one and write its placement record.

    Raises OnyxError SANDBOX_CAPACITY_UNAVAILABLE (no node accepts) or CONFLICT
    (a VM of another attempt holds the sandbox), and
    SandboxProvisionContentionError when another placement holds the lock.
    """
    with sandbox_placement_lock(
        tenant_cache, request.sandbox_id, blocking=True
    ) as lock:
        if lock is None:
            raise SandboxProvisionContentionError(str(request.sandbox_id))
        existing = _existing_vm(shared_cache, tenant_cache, client_factory, request)
        if existing is not None:
            record_placement(
                shared_cache,
                tenant_cache,
                tenant_id=request.tenant_id,
                sandbox_id=request.sandbox_id,
                placement=SandboxPlacement(
                    node_id=existing.node.node_id, generation=existing.vm.generation
                ),
            )
            return existing

        nodes = list_registered_nodes(shared_cache)
        placed = _place_new(
            client_factory, request, nodes, lock, rng or random.Random()
        )
        record_placement(
            shared_cache,
            tenant_cache,
            tenant_id=request.tenant_id,
            sandbox_id=request.sandbox_id,
            placement=SandboxPlacement(
                node_id=placed.node.node_id, generation=placed.vm.generation
            ),
        )
        logger.info(
            "sandbox_fc_placed node=%s sandbox=%s attempt=%d generation=%d created=%s",
            placed.node.node_id,
            request.sandbox_id,
            request.attempt,
            placed.vm.generation,
            placed.created,
        )
        return placed
