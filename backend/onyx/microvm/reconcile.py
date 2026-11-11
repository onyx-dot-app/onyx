"""Reconcile one node's VMs against the durable placement records (ENG-4576).

Each node agent pushes its full state every `--state-report-interval` (20 s):
`vms` (its `List`: live and exited VMs) and `ended` (VM instances that ended
within its `--ended-retention`). The report route runs one pass per node
under a per-node lease (`onyx.microvm.node_report`). The agent pushes
reports instead of a poll loop (microvm/README.md, "Sandbox state model"). Records
have no TTL, so a pass that runs out of time loses nothing; the next report
goes on.

Per reported VM:
- The record names it: keep it. A running VM goes to the idle evictor. An
  exited VM ended: clear its record and stop it (frees the node).
- The record or the reservation has a newer attempt, or the record names
  another instance of the same attempt: a stale orphan. Stop it.
- The reservation names (attempt, node) and the attempt's daemon key exists:
  adopt it with a fenced record write once the guest daemon accepts the key
  (Health shows that the guest answers; a repeat Create installs the key or
  is rejected when the guest holds another). A crash between Create and the
  record write, or a Create whose key install timed out, leaves this state.
  Adoptions run after the orphan stops, so a guest that does not answer
  cannot hold up cleanup. A pending key install waits `_ADOPT_RETRY_SECONDS`
  before the next try, and the least recently tried adoption runs first, so
  other adoptions get a turn. The key install calls end by the pass
  deadline; a cut call ends the pass and waits like a pending install, but
  does not start the give-up time.
- The reservation names it but its key is lost, the guest rejects the key,
  or the guest did not answer for `_ADOPT_GIVE_UP_SECONDS`: nothing can use
  it. It is an orphan after the grace period below.
- Anything else is unknown. It is an orphan once
  `SANDBOX_FC_ORPHAN_GRACE_SECONDS` passed since the first report of it.
Per ended VM: clear the record that names that instance (fenced).
Per indexed record of this node that names no reported VM: clear it after a
fresh `List` over mTLS, read under the sandbox lock (the report may predate a
new VM). If a `List` fails, the record stays, and the pass reads no more.
Orphan stops run at most `SANDBOX_FC_ORPHAN_STOPS_PER_REPORT` per pass, with
no checkpoint: a stale, unknown or unusable VM has no session that anyone can
use. Orphan stops and their last Health also end by the pass deadline; a cut
call ends the pass, and the next report finds the orphan again.
"""

import time
from collections.abc import Callable
from enum import Enum
from functools import partial
from uuid import UUID

import grpc
from pydantic import BaseModel, ConfigDict, SecretStr

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.microvm.agent_client import (
    GuestKeyRejectedError,
    HostAgentClientFactory,
    HostAgentConfigError,
    HostAgentError,
    HostAgentErrorReason,
)
from onyx.microvm.configs import (
    SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS,
    SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS,
    SANDBOX_FC_ORPHAN_GRACE_SECONDS,
    SANDBOX_FC_ORPHAN_STOPS_PER_REPORT,
)
from onyx.microvm.daemon_client import SandboxDaemonClient, SandboxDaemonError
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
_ADOPT_WAIT_PREFIX = "sandbox_fc:adopt_wait:"
# About three node reports.
_ADOPT_RETRY_SECONDS = 60
_ADOPT_GIVE_UP_SECONDS = 600
_ADOPT_WAIT_TTL_SECONDS = 3600
# A key install call needs at least this much of the pass deadline.
_MIN_CALL_SECONDS = 1.0


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


class _Adoption(BaseModel):
    model_config = ConfigDict(frozen=True)

    vm: AgentVm
    sandbox_id: UUID
    key: SecretStr
    reservation_raw: bytes
    last_try: int = 0


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


class _OutOfTime(Exception):
    """The pass deadline cut a key install call."""


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
        deadline: float | None,
    ) -> None:
        self.shared_cache = shared_cache
        self.client_factory = client_factory
        self.checkpointer = checkpointer
        self.activity = activity
        self.node = node
        self.now = now
        self.report = report
        self.check_lease = check_lease
        self.deadline = deadline
        self.stops: list[_OrphanStop] = []
        self.adoptions: list[_Adoption] = []
        self._stops_left = SANDBOX_FC_ORPHAN_STOPS_PER_REPORT
        self._list_failed = False

    def check(self) -> None:
        if self.check_lease is not None:
            try:
                self.check_lease()
            except Exception as e:
                raise _PassEnded(e) from e

    def _cut(self, default: float) -> tuple[float, bool]:
        """`call_timeout(default)` and whether the deadline cut it."""
        timeout = self.call_timeout(default)
        return timeout, timeout < default

    def call_timeout(self, default: float) -> float:
        """`default`, cut to the time left before the pass deadline. Raises
        `_OutOfTime` when too little time is left."""
        if self.deadline is None:
            return default
        left = self.deadline - time.monotonic()
        if left < _MIN_CALL_SECONDS:
            raise _OutOfTime()
        return min(default, left)

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

    def fresh_list(self) -> list[AgentVm] | None:
        """The node's List now. None after a failed List in this pass."""
        if self._list_failed:
            return None
        try:
            return self.client_factory.client(self.node.address).list_vms()
        except HostAgentError as e:
            self._list_failed = True
            logger.warning(
                "sandbox_fc_reconcile_node_unreachable node=%s error=%s",
                self.node.node_id,
                e,
            )
            return None

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
        self.run_stops()
        for adoption in sorted(self.adoptions, key=lambda a: a.last_try):
            self.step(
                f"adopt {self.node.node_id}/{adoption.vm.sandbox_id}",
                partial(self.adopt, adoption),
            )
        self.run_stops()

    def run_stops(self) -> None:
        stops, self.stops = self.stops, []
        for stop in stops[: self._stops_left]:
            self._stops_left -= 1
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
            key = get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=vm.attempt)
            wait = self.adopt_wait(vm)
            if key is None:
                self.stop_after_grace(vm, sandbox_id, "key_lost")
            elif (
                wait is not None
                and wait[0]
                and self.now - wait[0] >= _ADOPT_GIVE_UP_SECONDS
            ):
                self.stop_after_grace(vm, sandbox_id, "guest_unreachable")
            elif wait is None or self.now - wait[1] >= _ADOPT_RETRY_SECONDS:
                self.adoptions.append(
                    _Adoption(
                        vm=vm,
                        sandbox_id=sandbox_id,
                        key=key,
                        reservation_raw=found[1],
                        last_try=0 if wait is None else wait[1],
                    )
                )
            return
        if verdict is _Verdict.STALE:
            self.report.orphans_marked.append(vm.sandbox_id)
            self.stops.append(_OrphanStop(vm=vm, sandbox_id=sandbox_id, why="stale"))
            return
        self.stop_after_grace(vm, sandbox_id, "unknown")

    def stop_after_grace(self, vm: AgentVm, sandbox_id: UUID, why: str) -> None:
        first_seen = orphan_first_seen(
            self.shared_cache, self.node.node_id, vm, self.now
        )
        if self.now - first_seen >= SANDBOX_FC_ORPHAN_GRACE_SECONDS:
            self.report.orphans_marked.append(vm.sandbox_id)
            self.stops.append(_OrphanStop(vm=vm, sandbox_id=sandbox_id, why=why))

    def _adopt_wait_key(self, vm: AgentVm) -> str:
        return (
            f"{_ADOPT_WAIT_PREFIX}{self.node.node_id}:{vm.sandbox_id}:{vm.generation}"
        )

    def adopt_wait(self, vm: AgentVm) -> tuple[int, int] | None:
        """(first failed, last) time of the pending key installs of this VM.
        First is 0 while only the pass deadline cut the tries."""
        raw = self.shared_cache.get(self._adopt_wait_key(vm))
        if raw is None:
            return None
        first, _, last = raw.decode().partition(":")
        try:
            return int(first), int(last)
        except ValueError:
            return None

    def mark_adopt_wait(self, vm: AgentVm, *, failed: bool) -> None:
        wait = self.adopt_wait(vm)
        first = wait[0] if wait is not None and wait[0] else 0
        if failed and not first:
            first = self.now
        self.shared_cache.set(
            self._adopt_wait_key(vm),
            f"{first}:{self.now}",
            ex=_ADOPT_WAIT_TTL_SECONDS,
        )

    def adopt(self, adoption: _Adoption) -> None:
        """Write the record of a VM that its reservation names, once its
        guest daemon holds the attempt's key."""
        vm, sandbox_id = adoption.vm, adoption.sandbox_id
        tenant_cache = get_cache_backend(tenant_id=vm.tenant_id)
        with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=False) as lock:
            # A placement in progress writes the record itself.
            if lock is None:
                return
            try:
                installed = self.install_key(vm, adoption.key)
            except _OutOfTime as e:
                # Not a guest failure: the give-up time does not start.
                self.mark_adopt_wait(vm, failed=False)
                raise _PassEnded(TimeoutError("node report deadline exceeded")) from e
            if installed is None:
                # Keep the VM and the reservation: a later report or a wake
                # tries again.
                self.mark_adopt_wait(vm, failed=True)
                return
            if not installed:
                # The guest holds another key: nothing can use the VM.
                self.stop_after_grace(vm, sandbox_id, "key_rejected")
                return
            # A newer record won the fence: the next report stops this VM.
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
                return
            release_sandbox_reservation(
                tenant_cache, sandbox_id, adoption.reservation_raw
            )
        logger.info(
            "sandbox_fc_reconcile_adopted node=%s sandbox=%s attempt=%d generation=%d",
            self.node.node_id,
            sandbox_id,
            vm.attempt,
            vm.generation,
        )
        self.report.adopted.append(vm.sandbox_id)

    def install_key(self, vm: AgentVm, key: SecretStr) -> bool | None:
        """Make sure the guest daemon holds `key`. Health (no key) shows that
        the guest answers. A repeat Create of the same attempt returns the
        same VM and installs the key, or is rejected when the guest holds
        another key. None when the outcome is not known yet. Each call ends
        by the pass deadline; `_OutOfTime` when the deadline cut it."""
        client = self.client_factory.client(self.node.address)
        cut = False
        try:
            timeout, cut = self._cut(SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS)
            SandboxDaemonClient(
                client.channel, sandbox_id=vm.sandbox_id, sandboxd_key=key
            ).health(timeout=timeout)
            timeout, cut = self._cut(SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS)
            result = client.create(
                sandbox_id=vm.sandbox_id,
                attempt=vm.attempt,
                template=vm.template,
                vcpus=vm.vcpus,
                mem_mib=vm.mem_mib,
                scratch_gib=vm.scratch_gib,
                tenant_id=vm.tenant_id,
                sandboxd_key=key,
                timeout=timeout,
            )
        except GuestKeyRejectedError:
            return False
        except (HostAgentError, SandboxDaemonError) as e:
            if cut and e.code is grpc.StatusCode.DEADLINE_EXCEEDED:
                raise _OutOfTime() from e
            logger.warning(
                "sandbox_fc_reconcile_adopt_key_pending node=%s sandbox=%s attempt=%d error=%s",
                self.node.node_id,
                vm.sandbox_id,
                vm.attempt,
                e,
            )
            return None
        # Another VM instance: the next report adopts it.
        if result.vm.generation != vm.generation or not result.vm.state.is_live():
            return None
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
            # Placement writes the record under this lock, so a List read now
            # shows the VM of the record read now.
            placement = get_sandbox_placement(tenant_cache, sandbox_id)
            if placement is None or placement.node_id != self.node.node_id:
                return
            current = self.fresh_list()
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

    def still_unusable(self, stop: _OrphanStop, tenant_cache: CacheBackend) -> bool:
        """Under the sandbox lock: the reason that nothing can use a VM that
        its reservation names still holds. A wake can save the key meanwhile.
        A guest that rejected the key keeps the key that it holds."""
        if stop.why == "key_rejected":
            return True
        if stop.why == "guest_unreachable":
            return not self.guest_answers(stop, tenant_cache)
        return stop.why == "key_lost" and (
            get_sandbox_daemon_key(
                tenant_cache, stop.sandbox_id, attempt=stop.vm.attempt
            )
            is None
        )

    def guest_answers(self, stop: _OrphanStop, tenant_cache: CacheBackend) -> bool:
        """One more Health before a stop. A guest that answers gets new
        adoption tries."""
        vm = stop.vm
        key = get_sandbox_daemon_key(tenant_cache, stop.sandbox_id, attempt=vm.attempt)
        if key is None:
            return False
        client = self.client_factory.client(self.node.address)
        timeout, cut = self._cut(SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS)
        try:
            SandboxDaemonClient(
                client.channel, sandbox_id=vm.sandbox_id, sandboxd_key=key
            ).health(timeout=timeout)
        except (HostAgentError, SandboxDaemonError) as e:
            if cut and e.code is grpc.StatusCode.DEADLINE_EXCEEDED:
                raise _OutOfTime() from e
            return False
        self.shared_cache.delete(self._adopt_wait_key(vm))
        return True

    def stop_orphan(self, stop: _OrphanStop) -> None:
        try:
            self._stop_orphan(stop)
        except _OutOfTime as e:
            # The next report finds the orphan again.
            raise _PassEnded(TimeoutError("node report deadline exceeded")) from e

    def _stop_orphan(self, stop: _OrphanStop) -> None:
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
                if verdict is _Verdict.OWNED:
                    return
                if verdict is _Verdict.ADOPT and not self.still_unusable(
                    stop, tenant_cache
                ):
                    return
            timeout, cut = self._cut(SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS)
            try:
                self.client_factory.client(self.node.address).stop(
                    sandbox_id=vm.sandbox_id,
                    attempt=vm.attempt,
                    generation=vm.generation,
                    timeout=timeout,
                )
            except HostAgentError as e:
                if cut and e.code is grpc.StatusCode.DEADLINE_EXCEEDED:
                    raise _OutOfTime() from e
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
    deadline: float | None = None,
) -> ReconcileReport:
    """One reconcile pass over the state that `node` reported. `check_lease`
    runs before each step and raises to end the pass. `deadline`
    (`time.monotonic()`) bounds the key install calls of adoptions; a call
    that the deadline cuts ends the pass with `TimeoutError`.
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
        deadline,
    )
    try:
        run.run(vms, ended or [])
    except _PassEnded as ended_pass:
        raise ended_pass.cause from None
    return report
