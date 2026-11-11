"""Reconcile one node's VMs against the durable placement records (ENG-4576).

Each node agent pushes its full state every `--state-report-interval` (20 s):
`vms` (its `List`: live and exited VMs) and `ended` (VM instances that ended
within its `--ended-retention`). The report route runs one pass per node
under a per-node lease (`onyx.microvm.node_report`). This is E2B's sync with
a push instead of a pull (microvm/README.md, "Sandbox state model"). Records
have no TTL, so a pass that runs out of time loses nothing; the next report
goes on.

Per reported VM:
- The record names it: keep it. A running VM goes to the idle evictor. An
  exited VM ended: clear its record and stop it (frees the node).
- The record or the reservation has a newer attempt, or the record names
  another instance of the same attempt: a stale orphan. Stop it.
- The reservation names (attempt, node) and the attempt's daemon key exists:
  adopt it with a fenced record write. A crash between Create and the record
  write leaves this state.
- Anything else is unknown. It is an orphan once
  `SANDBOX_FC_ORPHAN_GRACE_SECONDS` passed since the first report of it.
Per ended VM: clear the record that names that instance (fenced).
Per indexed record of this node that names no reported VM: clear it after a
second `List` over mTLS (the report may predate a new VM). If that `List`
fails, the record stays.
Orphan stops run last, at most `SANDBOX_FC_ORPHAN_STOPS_PER_REPORT` per pass,
with no checkpoint: a stale or unknown VM has no session that anyone can use.
"""

import time
from collections.abc import Callable
from enum import Enum
from functools import partial
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.microvm.agent_client import (
    HostAgentClientFactory,
    HostAgentConfigError,
    HostAgentError,
    HostAgentErrorReason,
)
from onyx.microvm.configs import (
    SANDBOX_FC_ORPHAN_GRACE_SECONDS,
    SANDBOX_FC_ORPHAN_STOPS_PER_REPORT,
)
from onyx.microvm.lifecycle import (
    SandboxActivityProbe,
    SandboxCheckpointer,
    VmStopOutcome,
    evict_idle_sandbox_vm,
)
from onyx.microvm.models import (
    AgentVm,
    ReconcileReport,
    RegisteredNode,
    ReportedEndedVm,
    VmState,
)
from onyx.microvm.placement import (
    find_vm,
    forget_placement,
    record_placement,
    sandbox_placement_lock,
)
from onyx.microvm.registry import (
    SandboxPlacement,
    SandboxReservation,
    get_sandbox_daemon_key,
    get_sandbox_placement,
    get_sandbox_reservation,
    list_indexed_placements,
    release_sandbox_reservation,
    unindex_sandbox_placement,
)
from onyx.sandbox_proxy.sandbox_identity.signed import is_allowed_tenant_id
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ORPHAN_MARK_PREFIX = "sandbox_fc:orphan:"
_ORPHAN_MARK_TTL_SECONDS = 7 * 24 * 3600


class _Verdict(str, Enum):
    OWNED = "owned"
    ADOPT = "adopt"
    STALE = "stale"
    UNKNOWN = "unknown"


def _verdict(
    node_id: str,
    vm: AgentVm,
    record: SandboxPlacement | None,
    reservation: SandboxReservation | None,
) -> _Verdict:
    if record is not None:
        if record.names(node_id, vm.attempt, vm.generation):
            return _Verdict.OWNED
        if record.attempt >= vm.attempt:
            return _Verdict.STALE
    if reservation is not None:
        if reservation.attempt > vm.attempt:
            return _Verdict.STALE
        if (
            reservation.attempt == vm.attempt
            and reservation.node_id == node_id
            and vm.state.is_live()
        ):
            return _Verdict.ADOPT
    return _Verdict.UNKNOWN


class _OrphanStop(BaseModel):
    model_config = ConfigDict(frozen=True)

    vm: AgentVm
    sandbox_id: UUID
    why: str


def orphan_first_seen(
    shared_cache: CacheBackend, node_id: str, vm: AgentVm, now: int
) -> int:
    """When the api_server first saw this unknown VM (its own clock)."""
    key = f"{_ORPHAN_MARK_PREFIX}{node_id}:{vm.sandbox_id}:{vm.generation}"
    if shared_cache.set_if_absent(key, str(now), ex=_ORPHAN_MARK_TTL_SECONDS):
        logger.warning(
            "sandbox_fc_unknown_vm node=%s sandbox=%s tenant=%s attempt=%d generation=%d state=%s",
            node_id,
            vm.sandbox_id,
            vm.tenant_id,
            vm.attempt,
            vm.generation,
            vm.state.value,
        )
        return now
    raw = shared_cache.get(key)
    return int(raw) if raw is not None else now


class _PassEnded(Exception):
    """`check_lease` or a configuration error: end the whole pass with
    `cause`."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause


class _Pass:
    def __init__(
        self,
        shared_cache: CacheBackend,
        client_factory: HostAgentClientFactory,
        checkpointer: SandboxCheckpointer,
        activity: SandboxActivityProbe,
        node: RegisteredNode,
        now: int,
        report: ReconcileReport,
        check_lease: Callable[[], None] | None,
    ) -> None:
        self.shared_cache = shared_cache
        self.client_factory = client_factory
        self.checkpointer = checkpointer
        self.activity = activity
        self.node = node
        self.now = now
        self.report = report
        self.check_lease = check_lease
        self.stops: list[_OrphanStop] = []
        # The second List of this pass, read at most once.
        self._second_list: list[AgentVm] | None = None
        self._second_list_read = False

    def check(self) -> None:
        if self.check_lease is not None:
            try:
                self.check_lease()
            except Exception as e:
                raise _PassEnded(e) from e

    def step(self, what: str, run: Callable[[], None]) -> None:
        """Check the lease, then run one step. A failed step is logged and
        does not end the pass; a lease failure or missing mTLS settings do."""
        self.check()
        try:
            run()
        except _PassEnded:
            raise
        except HostAgentConfigError as e:
            raise _PassEnded(e) from e
        except Exception:
            logger.exception("sandbox_fc_reconcile_step_failed step=%s", what)
            self.report.failed.append(what)

    def second_list(self) -> list[AgentVm] | None:
        if not self._second_list_read:
            self._second_list_read = True
            try:
                self._second_list = self.client_factory.client(
                    self.node.address
                ).list_vms()
            except HostAgentError as e:
                logger.warning(
                    "sandbox_fc_reconcile_node_unreachable node=%s error=%s",
                    self.node.node_id,
                    e,
                )
        return self._second_list

    def valid(self, sandbox_id: str, tenant_id: str) -> UUID | None:
        try:
            parsed = UUID(sandbox_id)
        except ValueError:
            logger.error(
                "sandbox_fc_reconcile_bad_sandbox_id node=%s id=%r",
                self.node.node_id,
                sandbox_id,
            )
            return None
        if not is_allowed_tenant_id(tenant_id):
            logger.error(
                "sandbox_fc_reconcile_bad_tenant_id node=%s sandbox=%s tenant=%r",
                self.node.node_id,
                sandbox_id,
                tenant_id,
            )
            return None
        return parsed

    def run(self, vms: list[AgentVm], ended: list[ReportedEndedVm]) -> None:
        reported: set[tuple[str, int]] = set()
        for vm in vms:
            sandbox_id = self.valid(vm.sandbox_id, vm.tenant_id)
            if sandbox_id is None:
                continue
            if vm.state.is_live():
                reported.add((vm.sandbox_id, vm.generation))
            self.step(
                f"vm {self.node.node_id}/{vm.sandbox_id}",
                partial(self.vm, vm, sandbox_id),
            )
        for gone in ended:
            sandbox_id = self.valid(gone.sandbox_id, gone.tenant_id)
            if sandbox_id is None:
                continue
            self.step(
                f"ended {self.node.node_id}/{gone.sandbox_id}",
                partial(self.ended, gone, sandbox_id),
            )
        for indexed in list_indexed_placements(self.shared_cache, self.node.node_id):
            self.step(
                f"record {self.node.node_id}/{indexed.sandbox_id}",
                partial(self.record, indexed.tenant_id, indexed.sandbox_id, reported),
            )
        for stop in self.stops[:SANDBOX_FC_ORPHAN_STOPS_PER_REPORT]:
            self.step(
                f"orphan {self.node.node_id}/{stop.vm.sandbox_id}",
                partial(self.stop_orphan, stop),
            )

    def vm(self, vm: AgentVm, sandbox_id: UUID) -> None:
        tenant_cache = get_cache_backend(tenant_id=vm.tenant_id)
        record = get_sandbox_placement(tenant_cache, sandbox_id)
        found = get_sandbox_reservation(tenant_cache, sandbox_id)
        verdict = _verdict(
            self.node.node_id, vm, record, found[0] if found is not None else None
        )
        if verdict is _Verdict.OWNED and record is not None:
            if vm.state is VmState.EXITED:
                self.clear(
                    tenant_cache,
                    vm.tenant_id,
                    sandbox_id,
                    attempt=vm.attempt,
                    generation=vm.generation,
                )
                self.stops.append(
                    _OrphanStop(vm=vm, sandbox_id=sandbox_id, why="exited")
                )
            elif vm.state is VmState.RUNNING:
                self.evict_if_idle(vm, sandbox_id, tenant_cache, record)
            return
        if verdict is _Verdict.ADOPT and found is not None:
            if self.adopt(vm, sandbox_id, tenant_cache, found[1]):
                return
            verdict = _Verdict.UNKNOWN
        if verdict is _Verdict.STALE:
            self.report.orphans_marked.append(vm.sandbox_id)
            self.stops.append(_OrphanStop(vm=vm, sandbox_id=sandbox_id, why="stale"))
            return
        first_seen = orphan_first_seen(
            self.shared_cache, self.node.node_id, vm, self.now
        )
        if self.now - first_seen >= SANDBOX_FC_ORPHAN_GRACE_SECONDS:
            self.report.orphans_marked.append(vm.sandbox_id)
            self.stops.append(_OrphanStop(vm=vm, sandbox_id=sandbox_id, why="unknown"))

    def adopt(
        self,
        vm: AgentVm,
        sandbox_id: UUID,
        tenant_cache: CacheBackend,
        reservation_raw: bytes,
    ) -> bool:
        """Write the record of a VM that its reservation names. False when
        the daemon key is lost (nothing can use the VM)."""
        if get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt) is None:
            return False
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
            # A placement in progress writes the record itself.
            if lock is None:
                return True
            if not record_placement(
                self.shared_cache,
                tenant_cache,
                tenant_id=vm.tenant_id,
                sandbox_id=sandbox_id,
                placement=SandboxPlacement(
                    node_id=self.node.node_id,
                    attempt=vm.attempt,
                    generation=vm.generation,
                    last_active=self.now,
                ),
            ):
                return False
            release_sandbox_reservation(tenant_cache, sandbox_id, reservation_raw)
        logger.info(
            "sandbox_fc_reconcile_adopted node=%s sandbox=%s attempt=%d generation=%d",
            self.node.node_id,
            sandbox_id,
            vm.attempt,
            vm.generation,
        )
        self.report.adopted.append(vm.sandbox_id)
        return True

    def clear(
        self,
        tenant_cache: CacheBackend,
        tenant_id: str,
        sandbox_id: UUID,
        *,
        attempt: int,
        generation: int,
    ) -> None:
        if forget_placement(
            self.shared_cache,
            tenant_cache,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            node_id=self.node.node_id,
            attempt=attempt,
            generation=generation,
        ):
            logger.info(
                "sandbox_fc_reconcile_cleared node=%s sandbox=%s attempt=%d generation=%d",
                self.node.node_id,
                sandbox_id,
                attempt,
                generation,
            )
            self.report.cleared.append(str(sandbox_id))

    def ended(self, gone: ReportedEndedVm, sandbox_id: UUID) -> None:
        self.clear(
            get_cache_backend(tenant_id=gone.tenant_id),
            gone.tenant_id,
            sandbox_id,
            attempt=gone.attempt,
            generation=gone.generation,
        )

    def record(
        self, tenant_id: str, sandbox_id: UUID, reported: set[tuple[str, int]]
    ) -> None:
        tenant_cache = get_cache_backend(tenant_id=tenant_id)
        placement = get_sandbox_placement(tenant_cache, sandbox_id)
        if placement is None or placement.node_id != self.node.node_id:
            unindex_sandbox_placement(
                self.shared_cache,
                node_id=self.node.node_id,
                tenant_id=tenant_id,
                sandbox_id=sandbox_id,
            )
            return
        if (str(sandbox_id), placement.generation) in reported:
            return
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
            if lock is None:
                return
            # Check liveness again: the report may predate a new VM.
            current = self.second_list()
            if current is None:
                return
            vm = find_vm(current, sandbox_id, placement.generation)
            if vm is not None and vm.state.is_live():
                return
            self.clear(
                tenant_cache,
                tenant_id,
                sandbox_id,
                attempt=placement.attempt,
                generation=placement.generation,
            )

    def evict_if_idle(
        self,
        vm: AgentVm,
        sandbox_id: UUID,
        tenant_cache: CacheBackend,
        record: SandboxPlacement,
    ) -> None:
        outcome = evict_idle_sandbox_vm(
            self.shared_cache,
            tenant_cache,
            self.client_factory,
            self.checkpointer,
            self.activity,
            tenant_id=vm.tenant_id,
            sandbox_id=sandbox_id,
            last_active=record.last_active,
            now=self.now,
        )
        if outcome is VmStopOutcome.NOT_IDLE:
            return
        self.report.idle.append(vm.sandbox_id)
        if outcome is VmStopOutcome.STOPPED:
            self.report.slept.append(vm.sandbox_id)

    def stop_orphan(self, stop: _OrphanStop) -> None:
        vm, sandbox_id = stop.vm, stop.sandbox_id
        tenant_cache = get_cache_backend(tenant_id=vm.tenant_id)
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
            # A placement in progress may own this VM: next report.
            if lock is None:
                return
            if stop.why != "exited":
                found = get_sandbox_reservation(tenant_cache, sandbox_id)
                verdict = _verdict(
                    self.node.node_id,
                    vm,
                    get_sandbox_placement(tenant_cache, sandbox_id),
                    found[0] if found is not None else None,
                )
                if verdict in (_Verdict.OWNED, _Verdict.ADOPT):
                    return
            try:
                self.client_factory.client(self.node.address).stop(
                    sandbox_id=vm.sandbox_id,
                    attempt=vm.attempt,
                    generation=vm.generation,
                )
            except HostAgentError as e:
                if e.reason in (
                    HostAgentErrorReason.SANDBOX_NOT_FOUND,
                    HostAgentErrorReason.INSTANCE_MISMATCH,
                ):
                    return
                logger.warning(
                    "sandbox_fc_orphan_stop_failed node=%s sandbox=%s error=%s",
                    self.node.node_id,
                    sandbox_id,
                    e,
                )
                return
        logger.warning(
            "sandbox_fc_orphan_stopped node=%s sandbox=%s attempt=%d generation=%d why=%s",
            self.node.node_id,
            sandbox_id,
            vm.attempt,
            vm.generation,
            stop.why,
        )
        self.report.orphans_stopped.append(vm.sandbox_id)


def reconcile_node(
    shared_cache: CacheBackend,
    client_factory: HostAgentClientFactory,
    checkpointer: SandboxCheckpointer,
    activity: SandboxActivityProbe,
    *,
    node: RegisteredNode,
    vms: list[AgentVm],
    ended: list[ReportedEndedVm] | None = None,
    now: int | None = None,
    check_lease: Callable[[], None] | None = None,
) -> ReconcileReport:
    """One reconcile pass over the state that `node` reported. `check_lease`
    runs before each step and raises to end the pass.
    `HostAgentConfigError` also ends the pass and is raised. Any other error
    ends only its step."""
    report = ReconcileReport()
    run = _Pass(
        shared_cache,
        client_factory,
        checkpointer,
        activity,
        node,
        int(time.time()) if now is None else now,
        report,
        check_lease,
    )
    try:
        run.run(vms, ended or [])
    except _PassEnded as ended_pass:
        raise ended_pass.cause from None
    return report
