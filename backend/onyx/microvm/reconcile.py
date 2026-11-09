"""Two-way reconcile of host agent VMs and placement records (ENG-4576).

One pass, cluster-wide, run by the `microvm_reconcile` beat task under a lease:

- A live VM whose record matches: refresh the record TTL, then apply the idle
  sleep rules.
- A live VM without a record, whose sandbox row is at that attempt and still
  PROVISIONING or RUNNING, and whose guest daemon key is stored: write the
  record (adopt it). Placement can lose the record write after Create, for
  example on a crash.
- Any other live VM is an orphan: mark it. Stop it only after a saved
  checkpoint and a second liveness check. Without checkpoint support
  (before ENG-4580) orphans are only marked.
- A record whose VM is gone or exited: clear it, after a second `List` of the
  node. Records on a node that does not answer stay; their TTL ends them.
"""

import time
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import SandboxStatus
from onyx.microvm.agent_client import (
    AgentVm,
    HostAgentClientFactory,
    HostAgentError,
    VmState,
)
from onyx.microvm.lifecycle import (
    SandboxActivityProbe,
    SandboxCheckpointer,
    VmStopOutcome,
    sleep_idle_sandbox_vm,
)
from onyx.microvm.placement import (
    find_vm,
    forget_placement,
    record_placement,
    sandbox_placement_lock,
)
from onyx.microvm.registry import (
    RegisteredNode,
    SandboxPlacement,
    get_sandbox_daemon_key,
    get_sandbox_placement,
    list_indexed_placements,
    list_registered_nodes,
    unindex_sandbox_placement,
)
from onyx.server.features.build.db.sandbox import get_sandbox_by_id
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ORPHAN_MARK_PREFIX = "sandbox_fc:orphan:"
_ORPHAN_MARK_TTL_SECONDS = 7 * 24 * 3600
_ADOPTABLE_STATUSES = frozenset({SandboxStatus.PROVISIONING, SandboxStatus.RUNNING})


class ReconcileReport(BaseModel):
    nodes: int = 0
    unreachable_nodes: list[str] = Field(default_factory=list)
    refreshed: list[str] = Field(default_factory=list)
    adopted: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    orphans_marked: list[str] = Field(default_factory=list)
    orphans_stopped: list[str] = Field(default_factory=list)
    slept: list[str] = Field(default_factory=list)


class _SandboxRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: SandboxStatus
    attempt: int
    last_heartbeat: datetime | None
    created_at: datetime


def _load_sandbox_row(tenant_id: str, sandbox_id: UUID) -> _SandboxRow | None:
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        sandbox = get_sandbox_by_id(db_session, sandbox_id)
        if sandbox is None:
            return None
        return _SandboxRow(
            status=sandbox.status,
            attempt=sandbox.provisioning_attempt_number,
            last_heartbeat=sandbox.last_heartbeat,
            created_at=sandbox.created_at,
        )


def mark_orphan(shared_cache: CacheBackend, node_id: str, vm: AgentVm) -> bool:
    """Record when an orphan was first seen. True on the first sighting."""
    first = shared_cache.set_if_absent(
        f"{_ORPHAN_MARK_PREFIX}{node_id}:{vm.sandbox_id}:{vm.generation}",
        str(int(time.time())),
        ex=_ORPHAN_MARK_TTL_SECONDS,
    )
    if first:
        logger.warning(
            "sandbox_fc_orphan_vm node=%s sandbox=%s tenant=%s attempt=%d generation=%d state=%s",
            node_id,
            vm.sandbox_id,
            vm.tenant_id,
            vm.attempt,
            vm.generation,
            vm.state.value,
        )
    return first


def is_orphan_marked(shared_cache: CacheBackend, node_id: str, vm: AgentVm) -> bool:
    return shared_cache.exists(
        f"{_ORPHAN_MARK_PREFIX}{node_id}:{vm.sandbox_id}:{vm.generation}"
    )


class _Pass:
    def __init__(
        self,
        shared_cache: CacheBackend,
        client_factory: HostAgentClientFactory,
        checkpointer: SandboxCheckpointer,
        activity: SandboxActivityProbe,
        now: datetime,
        report: ReconcileReport,
    ) -> None:
        self.shared_cache = shared_cache
        self.client_factory = client_factory
        self.checkpointer = checkpointer
        self.activity = activity
        self.now = now
        self.report = report

    def list_vms(self, node: RegisteredNode) -> list[AgentVm] | None:
        try:
            return self.client_factory.client(node.address).list_vms()
        except HostAgentError as e:
            logger.warning(
                "sandbox_fc_reconcile_node_unreachable node=%s error=%s",
                node.node_id,
                e,
            )
            return None

    def node(self, node: RegisteredNode) -> None:
        vms = self.list_vms(node)
        if vms is None:
            self.report.unreachable_nodes.append(node.node_id)
            return
        for vm in vms:
            try:
                sandbox_id = UUID(vm.sandbox_id)
            except ValueError:
                logger.error(
                    "sandbox_fc_reconcile_bad_sandbox_id node=%s id=%r",
                    node.node_id,
                    vm.sandbox_id,
                )
                continue
            self.vm(node, vm, sandbox_id)
        live = {(vm.sandbox_id, vm.generation) for vm in vms if vm.state.is_live()}
        for indexed in list_indexed_placements(self.shared_cache, node.node_id):
            self.record(node, indexed.tenant_id, indexed.sandbox_id, live)

    def vm(self, node: RegisteredNode, vm: AgentVm, sandbox_id: UUID) -> None:
        tenant_cache = get_cache_backend(tenant_id=vm.tenant_id)
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        matches = placement == SandboxPlacement(
            node_id=node.node_id, generation=vm.generation
        )
        if not vm.state.is_live():
            # An exited VM has no files left; the record step clears its record.
            return
        if matches:
            record_placement(
                self.shared_cache,
                tenant_cache,
                tenant_id=vm.tenant_id,
                sandbox_id=sandbox_id,
                placement=SandboxPlacement(
                    node_id=node.node_id, generation=vm.generation
                ),
            )
            self.report.refreshed.append(vm.sandbox_id)
            if vm.state is VmState.RUNNING:
                self.maybe_sleep(vm, sandbox_id, tenant_cache)
            return

        row = _load_sandbox_row(vm.tenant_id, sandbox_id)
        if (
            placement is None
            and row is not None
            and row.status in _ADOPTABLE_STATUSES
            and row.attempt == vm.attempt
            # Without the key nothing can use the VM.
            and get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt)
            is not None
        ):
            with sandbox_placement_lock(
                tenant_cache, sandbox_id, blocking=False
            ) as lock:
                # A placement in progress writes the record itself.
                if lock is None or get_sandbox_placement(tenant_cache, sandbox_id):
                    return
                record_placement(
                    self.shared_cache,
                    tenant_cache,
                    tenant_id=vm.tenant_id,
                    sandbox_id=sandbox_id,
                    placement=SandboxPlacement(
                        node_id=node.node_id, generation=vm.generation
                    ),
                )
            logger.info(
                "sandbox_fc_reconcile_adopted node=%s sandbox=%s generation=%d",
                node.node_id,
                sandbox_id,
                vm.generation,
            )
            self.report.adopted.append(vm.sandbox_id)
            return

        mark_orphan(self.shared_cache, node.node_id, vm)
        self.report.orphans_marked.append(vm.sandbox_id)
        self.maybe_stop_orphan(node, vm, sandbox_id, tenant_cache)

    def maybe_stop_orphan(
        self,
        node: RegisteredNode,
        vm: AgentVm,
        sandbox_id: UUID,
        tenant_cache: CacheBackend,
    ) -> None:
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
            if lock is None:
                return
            if not self.checkpointer.save_checkpoint(
                tenant_id=vm.tenant_id, sandbox_id=sandbox_id, vm=vm
            ):
                return
            current = self.list_vms(node)
            again = (
                find_vm(current, sandbox_id, vm.generation)
                if current is not None
                else None
            )
            placement = get_sandbox_placement(tenant_cache, sandbox_id)
            if (
                again is None
                or not again.state.is_live()
                or placement
                == SandboxPlacement(node_id=node.node_id, generation=vm.generation)
            ):
                return
            try:
                self.client_factory.client(node.address).stop(
                    sandbox_id=vm.sandbox_id,
                    attempt=again.attempt,
                    generation=again.generation,
                )
            except HostAgentError as e:
                logger.warning(
                    "sandbox_fc_orphan_stop_failed node=%s sandbox=%s error=%s",
                    node.node_id,
                    sandbox_id,
                    e,
                )
                return
        self.report.orphans_stopped.append(vm.sandbox_id)

    def maybe_sleep(
        self, vm: AgentVm, sandbox_id: UUID, tenant_cache: CacheBackend
    ) -> None:
        row = _load_sandbox_row(vm.tenant_id, sandbox_id)
        if row is None:
            return
        outcome = sleep_idle_sandbox_vm(
            self.shared_cache,
            tenant_cache,
            self.client_factory,
            self.checkpointer,
            self.activity,
            tenant_id=vm.tenant_id,
            sandbox_id=sandbox_id,
            last_heartbeat=row.last_heartbeat,
            created_at=row.created_at,
            now=self.now,
        )
        if outcome is VmStopOutcome.STOPPED:
            self.report.slept.append(vm.sandbox_id)

    def record(
        self,
        node: RegisteredNode,
        tenant_id: str,
        sandbox_id: UUID,
        live: set[tuple[str, int]],
    ) -> None:
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None or placement.node_id != node.node_id:
            unindex_sandbox_placement(
                self.shared_cache,
                node_id=node.node_id,
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
            )
            return
        if (str(sandbox_id), placement.generation) in live:
            return
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
            if (
                lock is None
                or get_sandbox_placement(tenant_cache, sandbox_id) != placement
            ):
                return
            # Check liveness again: the first List may predate a new VM.
            current = self.list_vms(node)
            if current is None:
                return
            vm = find_vm(current, sandbox_id, placement.generation)
            if vm is not None and vm.state.is_live():
                return
            forget_placement(
                self.shared_cache,
                tenant_cache,
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
                node_id=node.node_id,
            )
        logger.info(
            "sandbox_fc_reconcile_cleared node=%s sandbox=%s generation=%d",
            node.node_id,
            sandbox_id,
            placement.generation,
        )
        self.report.cleared.append(str(sandbox_id))


def reconcile_microvms(
    shared_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    checkpointer: SandboxCheckpointer,
    activity: SandboxActivityProbe,
    *,
    now: datetime,
    check_lease: Callable[[], None] | None = None,
) -> ReconcileReport:
    """One reconcile pass over every registered node. `check_lease` runs
    before each node and raises to end the pass."""
    report = ReconcileReport()
    run = _Pass(shared_cache, client_factory, checkpointer, activity, now, report)
    for node in list_registered_nodes(shared_cache):
        if check_lease is not None:
            check_lease()
        report.nodes += 1
        run.node(node)
    return report
