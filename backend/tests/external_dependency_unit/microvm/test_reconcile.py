"""Per-node reconcile against Redis and fake host agents (ENG-4576).

Each pass gets the state that the node would report: its `List` and its
ended list. State model: microvm/README.md, "Sandbox state model".
"""

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import grpc
import pytest

from onyx.cache.interface import CacheBackend
from onyx.microvm import reconcile
from onyx.microvm.agent_client import (
    HostAgentClient,
    HostAgentClientFactory,
    HostAgentConfigError,
    new_sandboxd_key,
)
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.daemon_client import (
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
)
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    UnknownActivity,
)
from onyx.microvm.models import (
    AgentVm,
    EndedReason,
    IndexedPlacement,
    ReconcileReport,
    RegisteredNode,
    ReportedEndedVm,
)
from onyx.microvm.placement import record_placement, sandbox_placement_lock
from onyx.microvm.reconcile import reconcile_node
from onyx.microvm.registry import (
    SandboxPlacement,
    SandboxReservation,
    get_registered_node,
    get_sandbox_placement,
    get_sandbox_reservation,
    list_indexed_placements,
    reserve_sandbox,
    set_sandbox_daemon_key,
    write_sandbox_placement,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)

NOW = int(time.time())


class AlwaysSaved(SandboxCheckpointer):
    def save_checkpoint(self, *, tenant_id: str, sandbox_id: UUID, vm: AgentVm) -> bool:  # noqa: ARG002
        return True


class Quiet(SandboxActivityProbe):
    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:  # noqa: ARG002
        return False


def _node(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:6]}"


def _registered(shared_cache: CacheBackend, node_id: str) -> RegisteredNode:
    node = get_registered_node(shared_cache, node_id)
    assert node is not None
    return node


def _report(
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    node_id: str,
    *,
    ended: list[ReportedEndedVm] | None = None,
    vms: list[AgentVm] | None = None,
    checkpointer: SandboxCheckpointer | None = None,
    activity: SandboxActivityProbe | None = None,
    now: int = NOW,
) -> ReconcileReport:
    """One report of `node_id`: its List (or `vms`) and `ended`."""
    node = _registered(shared_cache, node_id)
    return reconcile_node(
        shared_cache,
        client_factory,
        checkpointer or NoCheckpointSupport(),
        activity or UnknownActivity(),
        node=node,
        vms=client_factory.client(node.address).list_vms() if vms is None else vms,
        ended=ended,
        now=now,
    )


def _place(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    node_id: str,
    *,
    attempt: int = 1,
    generation: int,
    last_active: int = NOW,
) -> None:
    assert record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        placement=SandboxPlacement(
            node_id=node_id,
            attempt=attempt,
            generation=generation,
            last_active=last_active,
        ),
    )


def _vm(
    node: RunningFakeAgent,
    sandbox_id: UUID,
    attempt: int = 1,
    state: hostagent_pb2.VMState = hostagent_pb2.VM_STATE_RUNNING,
) -> hostagent_pb2.VM:
    return node.agent.add_vm(
        sandbox_id=str(sandbox_id), tenant_id=TENANT_ID, attempt=attempt, state=state
    )


def _elsewhere(tenant_cache: CacheBackend, sandbox_id: UUID, attempt: int) -> None:
    """A record on another node, with no index entry to clean up."""
    assert write_sandbox_placement(
        tenant_cache,
        sandbox_id,
        SandboxPlacement(
            node_id="elsewhere", attempt=attempt, generation=1, last_active=NOW
        ),
    )


def test_record_without_vm_is_cleared_and_an_exited_vm_is_stopped(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("rec")
    node = add_node(node_id)
    gone_id, exited_id = new_sandbox_id(), new_sandbox_id()
    _place(shared_cache, tenant_cache, gone_id, node_id, generation=7)
    exited = _vm(node, exited_id, state=hostagent_pb2.VM_STATE_EXITED)
    _place(shared_cache, tenant_cache, exited_id, node_id, generation=exited.generation)

    report = _report(shared_cache, client_factory, node_id)

    assert sorted(report.cleared) == sorted([str(gone_id), str(exited_id)])
    assert get_sandbox_placement(tenant_cache, gone_id) is None
    assert get_sandbox_placement(tenant_cache, exited_id) is None
    assert list_indexed_placements(shared_cache, node_id) == []
    # The exited VM's own record named it: stop it to free the node.
    assert node.agent.stop_calls == [(str(exited_id), 1, exited.generation)]


def test_ended_list_clears_the_record_without_a_second_list(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("ended")
    node = add_node(node_id)
    sandbox_id, kept_id = new_sandbox_id(), new_sandbox_id()
    _place(shared_cache, tenant_cache, sandbox_id, node_id, attempt=2, generation=41)
    _place(shared_cache, tenant_cache, kept_id, node_id, generation=50)
    # The agent does not answer: only the ended list can clear a record.
    node.stop()
    ended = [
        ReportedEndedVm(
            sandbox_id=str(sandbox_id),
            tenant_id=TENANT_ID,
            attempt=2,
            generation=41,
            reason=EndedReason.STOPPED,
            ended_at=datetime.now(timezone.utc),
        ),
        # An older instance of the same sandbox changes nothing.
        ReportedEndedVm(
            sandbox_id=str(kept_id),
            tenant_id=TENANT_ID,
            attempt=1,
            generation=49,
            reason=EndedReason.EXITED,
            ended_at=datetime.now(timezone.utc),
        ),
    ]

    report = _report(shared_cache, client_factory, node_id, vms=[], ended=ended)

    assert report.cleared == [str(sandbox_id)]
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None
    kept = get_sandbox_placement(tenant_cache, kept_id)
    assert kept is not None and kept.generation == 50

    # The next report lists the same ended VM again: nothing changes.
    again = _report(shared_cache, client_factory, node_id, vms=[], ended=ended)
    assert again.cleared == []


def test_vm_named_by_its_reservation_is_adopted(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("adopt")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    # Placement crashed after Create and before the record write.
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=2, node_id=node_id, owner="crashed"),
        replaces=None,
    )
    key = new_sandboxd_key()
    set_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=2, key=key)
    vm = node.agent.add_vm(
        sandbox_id=str(sandbox_id),
        tenant_id=TENANT_ID,
        attempt=2,
        daemon_key=key.get_secret_value(),
    )

    report = _report(shared_cache, client_factory, node_id)

    assert report.adopted == [str(sandbox_id)]
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.names(node_id, 2, vm.generation)
    assert get_sandbox_reservation(tenant_cache, sandbox_id) is None
    # One repeat Create checks that the guest holds this key.
    assert node.agent.stop_calls == [] and node.agent.create_calls == 1
    assert _report(shared_cache, client_factory, node_id).adopted == []


def test_adoption_installs_the_key_that_the_daemon_did_not_take(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("adoptkey")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    # Create ran out of GUEST_UNREACHABLE retries: the VM runs, its daemon
    # has no key, and the reservation and the key stay.
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=2, node_id=node_id, owner="timed-out"),
        replaces=None,
    )
    key = new_sandboxd_key()
    set_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=2, key=key)
    vm = _vm(node, sandbox_id, attempt=2)
    node.agent.guest_unreachable_creates = 1

    # The daemon still does not take the key: keep the VM and the
    # reservation, so a wake repeats the same Create.
    first = _report(shared_cache, client_factory, node_id)
    assert first.adopted == [] and first.orphans_marked == []
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None
    assert get_sandbox_reservation(tenant_cache, sandbox_id) is not None
    assert node.agent.stop_calls == []
    # The pending install waits for its retry time.
    assert _report(shared_cache, client_factory, node_id).adopted == []
    assert node.agent.create_calls == 1

    second = _report(
        shared_cache,
        client_factory,
        node_id,
        now=NOW + reconcile._ADOPT_RETRY_SECONDS,
    )

    assert second.adopted == [str(sandbox_id)]
    assert node.agent.daemon_keys[str(sandbox_id)] == key.get_secret_value()
    assert [r[:2] for r in node.agent.create_requests] == [(str(sandbox_id), 2)] * 2
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.names(node_id, 2, vm.generation)
    assert get_sandbox_reservation(tenant_cache, sandbox_id) is None


def test_vm_without_its_daemon_key_is_not_adopted(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("nokey")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=1, node_id=node_id, owner="crashed"),
        replaces=None,
    )
    _vm(node, sandbox_id)

    report = _report(shared_cache, client_factory, node_id)

    assert report.adopted == []
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None
    # Inside the grace period: not stopped yet.
    assert node.agent.stop_calls == []

    # Nothing can use it, though its reservation names it.
    later = _report(
        shared_cache,
        client_factory,
        node_id,
        now=NOW + reconcile.SANDBOX_FC_ORPHAN_GRACE_SECONDS,
    )
    assert later.orphans_stopped == [str(sandbox_id)]
    assert node.agent.vms == {}


def test_vm_whose_key_is_saved_before_its_stop_is_kept(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _node("keysaved")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=1, node_id=node_id, owner="waking"),
        replaces=None,
    )
    _vm(node, sandbox_id)
    assert _report(shared_cache, client_factory, node_id).orphans_marked == []
    stop_orphan = reconcile._Pass.stop_orphan

    def wake_saves_key_first(
        self: reconcile._Pass, stop: reconcile._OrphanStop
    ) -> None:
        # A wake saves the key between the VM step and the stop.
        set_sandbox_daemon_key(
            tenant_cache, sandbox_id, attempt=1, key=new_sandboxd_key()
        )
        stop_orphan(self, stop)

    monkeypatch.setattr(reconcile._Pass, "stop_orphan", wake_saves_key_first)

    later = _report(
        shared_cache,
        client_factory,
        node_id,
        now=NOW + reconcile.SANDBOX_FC_ORPHAN_GRACE_SECONDS,
    )

    assert later.orphans_marked == [str(sandbox_id)]
    assert later.orphans_stopped == [] and node.agent.stop_calls == []


def test_vm_whose_guest_holds_another_key_is_stopped_after_the_grace_period(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("rejected")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=1, node_id=node_id, owner="crashed"),
        replaces=None,
    )
    # A retry saved a new key after the guest took the old one.
    set_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=1, key=new_sandboxd_key())
    node.agent.add_vm(
        sandbox_id=str(sandbox_id),
        tenant_id=TENANT_ID,
        attempt=1,
        daemon_key=new_sandboxd_key().get_secret_value(),
    )

    first = _report(shared_cache, client_factory, node_id)
    assert first.adopted == [] and node.agent.stop_calls == []

    later = _report(
        shared_cache,
        client_factory,
        node_id,
        now=NOW + reconcile.SANDBOX_FC_ORPHAN_GRACE_SECONDS,
    )
    assert later.adopted == []
    assert later.orphans_stopped == [str(sandbox_id)]
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None


def test_vm_whose_guest_never_answers_is_stopped_in_the_end(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _node("silent")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=1, node_id=node_id, owner="timed-out"),
        replaces=None,
    )
    set_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=1, key=new_sandboxd_key())
    _vm(node, sandbox_id)
    node.agent.guest_unreachable_creates = 100
    give_up = NOW + reconcile._ADOPT_GIVE_UP_SECONDS
    grace = reconcile.SANDBOX_FC_ORPHAN_GRACE_SECONDS

    assert _report(shared_cache, client_factory, node_id).adopted == []
    assert _report(shared_cache, client_factory, node_id, now=give_up).adopted == []

    # The guest answers Health again: keep the VM and try adoption again.
    kept = _report(shared_cache, client_factory, node_id, now=give_up + grace)
    assert kept.orphans_stopped == [] and node.agent.stop_calls == []
    tries = node.agent.create_calls
    _report(shared_cache, client_factory, node_id, now=give_up + grace + 1)
    assert node.agent.create_calls == tries + 1

    def no_answer(
        self: SandboxDaemonClient,  # noqa: ARG001
        timeout: float | None = None,  # noqa: ARG001
    ) -> None:
        raise SandboxDaemonError(
            grpc.StatusCode.UNAVAILABLE,
            "no answer",
            SandboxDaemonErrorReason.INTERNAL,
        )

    monkeypatch.setattr(SandboxDaemonClient, "health", no_answer)
    # The grace period already ran out at the first give-up.
    later = give_up + grace + 1 + reconcile._ADOPT_GIVE_UP_SECONDS
    stopped = _report(shared_cache, client_factory, node_id, now=later)

    assert stopped.orphans_stopped == [str(sandbox_id)]
    assert node.agent.vms == {}


def test_pending_key_install_does_not_hold_up_orphan_stops(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("pending")
    node = add_node(node_id)
    pending, stale = new_sandbox_id(), new_sandbox_id()
    reserve_sandbox(
        tenant_cache,
        pending,
        SandboxReservation(attempt=1, node_id=node_id, owner="timed-out"),
        replaces=None,
    )
    set_sandbox_daemon_key(tenant_cache, pending, attempt=1, key=new_sandboxd_key())
    _vm(node, pending)
    _vm(node, stale)
    _elsewhere(tenant_cache, stale, attempt=2)
    node.agent.guest_unreachable_creates = 10
    steps: list[int] = []

    def check_lease() -> None:
        steps.append(1)
        # Two VMs, then the orphan stop; the deadline hits before adoption.
        if len(steps) == 4:
            raise TimeoutError("deadline")

    registered = _registered(shared_cache, node_id)
    with pytest.raises(TimeoutError):
        reconcile_node(
            shared_cache,
            client_factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=registered,
            vms=client_factory.client(registered.address).list_vms(),
            now=NOW,
            check_lease=check_lease,
        )

    assert [c[0] for c in node.agent.stop_calls] == [str(stale)]
    assert node.agent.create_calls == 0


def test_key_install_ends_by_the_pass_deadline(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("deadline")
    node = add_node(node_id)
    slow, ready = new_sandbox_id(), new_sandbox_id()
    vms: dict[UUID, hostagent_pb2.VM] = {}
    for sandbox_id in (slow, ready):
        reserve_sandbox(
            tenant_cache,
            sandbox_id,
            SandboxReservation(attempt=1, node_id=node_id, owner="timed-out"),
            replaces=None,
        )
        set_sandbox_daemon_key(
            tenant_cache, sandbox_id, attempt=1, key=new_sandboxd_key()
        )
        vms[sandbox_id] = _vm(node, sandbox_id)
    registered = _registered(shared_cache, node_id)
    listed = {
        vm.sandbox_id: vm for vm in client_factory.client(registered.address).list_vms()
    }
    # The slow adoption runs first.
    ordered = [listed[str(slow)], listed[str(ready)]]
    # Slower than the time left in the pass, faster than the Create timeout.
    node.agent.create_delay_seconds = 4.0

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        reconcile_node(
            shared_cache,
            client_factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=registered,
            vms=ordered,
            now=NOW,
            deadline=started + 2.0,
        )

    assert time.monotonic() - started < 3.5
    assert get_sandbox_placement(tenant_cache, slow) is None
    assert get_sandbox_reservation(tenant_cache, slow) is not None
    node.agent.create_delay_seconds = 0.0
    # The cut adoption waits, so the next pass adopts the other VM.
    second = _report(shared_cache, client_factory, node_id, vms=ordered)
    assert second.adopted == [str(ready)]
    # A cut is not a guest failure: the give-up time has not started.
    third = _report(
        shared_cache,
        client_factory,
        node_id,
        vms=ordered,
        now=NOW + reconcile._ADOPT_GIVE_UP_SECONDS,
    )
    assert third.adopted == [str(slow)] and third.orphans_marked == []
    record = get_sandbox_placement(tenant_cache, slow)
    assert record is not None and record.names(node_id, 1, vms[slow].generation)


def test_orphan_stop_ends_by_the_pass_deadline(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("stopcut")
    node = add_node(node_id)
    stale = new_sandbox_id()
    _vm(node, stale)
    _elsewhere(tenant_cache, stale, attempt=2)
    # Slower than the time left in the pass, faster than the Stop timeout.
    node.agent.stop_delay_seconds = 4.0
    registered = _registered(shared_cache, node_id)

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        reconcile_node(
            shared_cache,
            client_factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=registered,
            vms=client_factory.client(registered.address).list_vms(),
            now=NOW,
            deadline=started + 2.0,
        )
    assert time.monotonic() - started < 3.5

    # Too little time left: the pass ends before the Stop call.
    with pytest.raises(TimeoutError):
        reconcile_node(
            shared_cache,
            client_factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=registered,
            vms=client_factory.client(registered.address).list_vms(),
            now=NOW,
            deadline=time.monotonic() + 0.5,
        )
    calls = len(node.agent.stop_calls)

    # The next report stops the orphan.
    node.agent.stop_delay_seconds = 0.0
    report = _report(shared_cache, client_factory, node_id)
    assert report.orphans_stopped == [str(stale)]
    assert len(node.agent.stop_calls) == calls + 1


def test_least_recently_tried_adoption_runs_first(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("rotate")
    node = add_node(node_id)
    recent, older = new_sandbox_id(), new_sandbox_id()
    for sandbox_id, last_try in ((recent, NOW - 60), (older, NOW - 120)):
        reserve_sandbox(
            tenant_cache,
            sandbox_id,
            SandboxReservation(attempt=1, node_id=node_id, owner="timed-out"),
            replaces=None,
        )
        set_sandbox_daemon_key(
            tenant_cache, sandbox_id, attempt=1, key=new_sandboxd_key()
        )
        vm = _vm(node, sandbox_id)
        shared_cache.set(
            f"{reconcile._ADOPT_WAIT_PREFIX}{node_id}:{sandbox_id}:{vm.generation}",
            f"{last_try}:{last_try}",
            ex=60,
        )
    listed = {
        vm.sandbox_id: vm
        for vm in client_factory.client(
            _registered(shared_cache, node_id).address
        ).list_vms()
    }

    report = _report(
        shared_cache,
        client_factory,
        node_id,
        vms=[listed[str(recent)], listed[str(older)]],
    )

    assert report.adopted == [str(older), str(recent)]
    assert [r[0] for r in node.agent.create_requests] == [str(older), str(recent)]


def test_stale_write_never_replaces_a_newer_record(
    tenant_cache: CacheBackend, new_sandbox_id: NewSandboxId
) -> None:
    sandbox_id = new_sandbox_id()
    newer = SandboxPlacement(node_id="b", attempt=3, generation=10, last_active=5)
    assert write_sandbox_placement(tenant_cache, sandbox_id, newer)
    for stale in (
        SandboxPlacement(node_id="a", attempt=2, generation=99, last_active=9),
        SandboxPlacement(node_id="a", attempt=3, generation=9, last_active=9),
    ):
        assert not write_sandbox_placement(tenant_cache, sandbox_id, stale)
    assert get_sandbox_placement(tenant_cache, sandbox_id) == newer
    # The same instance again keeps the later activity.
    assert write_sandbox_placement(
        tenant_cache, sandbox_id, newer.model_copy(update={"last_active": 2})
    )
    assert get_sandbox_placement(tenant_cache, sandbox_id) == newer
    newest = SandboxPlacement(node_id="a", attempt=4, generation=1, last_active=1)
    assert write_sandbox_placement(tenant_cache, sandbox_id, newest)
    assert get_sandbox_placement(tenant_cache, sandbox_id) == newest


def test_stale_report_cannot_adopt_over_a_newer_record(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    old_id, new_id = _node("old"), _node("new")
    old = add_node(old_id)
    add_node(new_id)
    sandbox_id = new_sandbox_id()
    stale = _vm(old, sandbox_id, attempt=2)
    set_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=2, key=new_sandboxd_key())
    # A leftover reservation names the old VM, but attempt 3 runs elsewhere.
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=2, node_id=old_id, owner="crashed"),
        replaces=None,
    )
    _place(shared_cache, tenant_cache, sandbox_id, new_id, attempt=3, generation=5)

    report = _report(shared_cache, client_factory, old_id)

    assert report.adopted == []
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.names(new_id, 3, 5)
    assert old.agent.stop_calls == [(str(sandbox_id), 2, stale.generation)]


def test_vm_of_an_older_attempt_is_stopped_at_once_without_checkpoint(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    """A dead node came back: its VM has an older attempt than the record."""
    back_id, live_id = _node("back"), _node("live")
    back = add_node(back_id)
    add_node(live_id)
    sandbox_id = new_sandbox_id()
    old = _vm(back, sandbox_id, attempt=1)
    _place(shared_cache, tenant_cache, sandbox_id, live_id, attempt=2, generation=3)

    report = _report(shared_cache, client_factory, back_id)

    assert report.orphans_marked == [str(sandbox_id)]
    assert report.orphans_stopped == [str(sandbox_id)]
    assert back.agent.stop_calls == [(str(sandbox_id), 1, old.generation)]
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.names(live_id, 2, 3)


def test_unknown_vm_is_stopped_after_the_grace_period(
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("unknown")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    vm = _vm(node, sandbox_id)

    first = _report(shared_cache, client_factory, node_id, now=NOW)
    assert first.orphans_stopped == [] and node.agent.stop_calls == []

    later = _report(
        shared_cache,
        client_factory,
        node_id,
        now=NOW + reconcile.SANDBOX_FC_ORPHAN_GRACE_SECONDS,
    )
    assert later.orphans_stopped == [str(sandbox_id)]
    assert node.agent.stop_calls == [(str(sandbox_id), 1, vm.generation)]


def test_orphan_stops_are_bounded_per_report(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reconcile, "SANDBOX_FC_ORPHAN_STOPS_PER_REPORT", 2)
    node_id = _node("bounded")
    node = add_node(node_id)
    for _ in range(3):
        sandbox_id = new_sandbox_id()
        _vm(node, sandbox_id, attempt=1)
        _elsewhere(tenant_cache, sandbox_id, attempt=2)

    assert len(_report(shared_cache, client_factory, node_id).orphans_stopped) == 2
    assert len(_report(shared_cache, client_factory, node_id).orphans_stopped) == 1
    assert node.agent.vms == {}


def test_orphan_is_not_stopped_while_a_placement_holds_the_sandbox(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("busy")
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    _vm(node, sandbox_id, attempt=1)
    _elsewhere(tenant_cache, sandbox_id, attempt=2)

    with sandbox_placement_lock(tenant_cache, sandbox_id, blocking=True):
        report = _report(shared_cache, client_factory, node_id)

    assert report.orphans_marked == [str(sandbox_id)]
    assert report.orphans_stopped == [] and node.agent.stop_calls == []


def test_record_stays_when_the_second_list_fails(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("down")
    add_node(node_id).stop()
    sandbox_id = new_sandbox_id()
    _place(shared_cache, tenant_cache, sandbox_id, node_id, generation=9)

    # The report does not list the VM, but the liveness check cannot reach
    # the agent: keep the record.
    report = _report(shared_cache, client_factory, node_id, vms=[])

    assert report.cleared == []
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.generation == 9


def test_record_of_a_vm_started_during_the_pass_is_kept(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _node("race")
    node = add_node(node_id)
    gone_id, woken_id = new_sandbox_id(), new_sandbox_id()
    _place(shared_cache, tenant_cache, gone_id, node_id, generation=3)
    _place(shared_cache, tenant_cache, woken_id, node_id, generation=4)
    monkeypatch.setattr(
        reconcile,
        "list_indexed_placements",
        lambda cache, node: [  # noqa: ARG005
            IndexedPlacement(tenant_id=TENANT_ID, sandbox_id=gone_id),
            IndexedPlacement(tenant_id=TENANT_ID, sandbox_id=woken_id),
        ],
    )
    real_list = HostAgentClient.list_vms
    started: list[hostagent_pb2.VM] = []

    def list_then_wake(client: HostAgentClient) -> list[AgentVm]:
        vms = real_list(client)
        if not started:
            # A wake replaces the second sandbox's VM after the first List.
            started.append(_vm(node, woken_id, attempt=2))
            _place(
                shared_cache,
                tenant_cache,
                woken_id,
                node_id,
                attempt=2,
                generation=started[0].generation,
            )
        return vms

    monkeypatch.setattr(HostAgentClient, "list_vms", list_then_wake)

    report = _report(shared_cache, client_factory, node_id, vms=[])

    assert report.cleared == [str(gone_id)]
    record = get_sandbox_placement(tenant_cache, woken_id)
    assert record is not None and record.names(node_id, 2, started[0].generation)


def test_idle_evictor_decides_but_keeps_the_vm_without_checkpoints(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("idle")
    node = add_node(node_id)
    idle_id, active_id = new_sandbox_id(), new_sandbox_id()
    idle = _vm(node, idle_id)
    active = _vm(node, active_id)
    old = NOW - SANDBOX_FC_IDLE_TIMEOUT_SECONDS - 1
    _place(
        shared_cache,
        tenant_cache,
        idle_id,
        node_id,
        generation=idle.generation,
        last_active=old,
    )
    _place(shared_cache, tenant_cache, active_id, node_id, generation=active.generation)

    # Until ENG-4580: the decision is made, the VM stays.
    report = _report(shared_cache, client_factory, node_id)
    assert report.idle == [str(idle_id)] and report.slept == []
    assert node.agent.stop_calls == []

    report = _report(
        shared_cache,
        client_factory,
        node_id,
        checkpointer=AlwaysSaved(),
        activity=Quiet(),
    )
    assert report.slept == [str(idle_id)]
    assert node.agent.stop_calls == [(str(idle_id), 1, idle.generation)]
    assert get_sandbox_placement(tenant_cache, idle_id) is None
    assert get_sandbox_placement(tenant_cache, active_id) is not None


def test_a_failing_vm_does_not_end_the_pass(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _node("isolate")
    node = add_node(node_id)
    broken, healthy = new_sandbox_id(), new_sandbox_id()
    for sandbox_id in (broken, healthy):
        _vm(node, sandbox_id, attempt=1)
        reserve_sandbox(
            tenant_cache,
            sandbox_id,
            SandboxReservation(attempt=1, node_id=node_id, owner="crashed"),
            replaces=None,
        )
        set_sandbox_daemon_key(
            tenant_cache, sandbox_id, attempt=1, key=new_sandboxd_key()
        )
    read = reconcile.get_sandbox_reservation

    def read_or_fail(
        cache: CacheBackend, sandbox_id: UUID
    ) -> tuple[SandboxReservation, bytes] | None:
        if sandbox_id == broken:
            raise RuntimeError("tenant cache is gone")
        return read(cache, sandbox_id)

    monkeypatch.setattr(reconcile, "get_sandbox_reservation", read_or_fail)

    report = _report(shared_cache, client_factory, node_id)

    assert report.adopted == [str(healthy)]
    assert len(report.failed) == 1 and str(broken) in report.failed[0]


def test_lease_is_checked_before_every_step(
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("lease")
    node = add_node(node_id)
    for _ in range(2):
        _vm(node, new_sandbox_id())
    checks: list[int] = []

    def check_lease() -> None:
        checks.append(1)
        # The first VM passes; the lease is lost before the second VM.
        if len(checks) == 2:
            raise TimeoutError("deadline")

    registered = _registered(shared_cache, node_id)
    with pytest.raises(TimeoutError):
        reconcile_node(
            shared_cache,
            client_factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=registered,
            vms=client_factory.client(registered.address).list_vms(),
            now=NOW,
            check_lease=check_lease,
        )
    assert len(checks) == 2


class _NoMtlsFactory(HostAgentClientFactory):
    def __init__(self) -> None:
        self.calls = 0

    def client(self, address: str) -> HostAgentClient:  # noqa: ARG002
        self.calls += 1
        raise HostAgentConfigError("SANDBOX_FC_AGENT_CLIENT_CERT_PATH must be set")


def test_missing_mtls_settings_end_the_pass_once(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("nomtls")
    add_node(node_id)
    # Two records without a VM: each needs the second List over mTLS.
    for sandbox_id in (new_sandbox_id(), new_sandbox_id()):
        _place(shared_cache, tenant_cache, sandbox_id, node_id, generation=3)
    factory = _NoMtlsFactory()

    with pytest.raises(HostAgentConfigError):
        reconcile_node(
            shared_cache,
            factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=_registered(shared_cache, node_id),
            vms=[],
            now=NOW,
        )
    assert factory.calls == 1
    assert len(list_indexed_placements(shared_cache, node_id)) == 2
