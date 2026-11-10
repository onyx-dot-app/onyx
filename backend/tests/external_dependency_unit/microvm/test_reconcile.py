"""Two-way reconcile against Postgres, Redis and fake host agents (ENG-4576)."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from onyx.cache.interface import CacheBackend
from onyx.db.enums import SandboxStatus
from onyx.microvm import reconcile
from onyx.microvm.agent_client import AgentVm, new_sandboxd_key
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    UnknownActivity,
)
from onyx.microvm.placement import record_placement
from onyx.microvm.reconcile import ReconcileReport, reconcile_microvms
from onyx.microvm.registry import (
    SandboxPlacement,
    get_sandbox_placement,
    list_indexed_placements,
    set_sandbox_daemon_key,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    MakeSandbox,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import InsecureClientFactory

NOW = datetime.now(timezone.utc)


class AlwaysSaved(SandboxCheckpointer):
    def save_checkpoint(self, *, tenant_id: str, sandbox_id: UUID, vm: AgentVm) -> bool:  # noqa: ARG002
        return True


class Quiet(SandboxActivityProbe):
    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:  # noqa: ARG002
        return False


def _reconcile(
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    checkpointer: SandboxCheckpointer | None = None,
    activity: SandboxActivityProbe | None = None,
) -> ReconcileReport:
    return reconcile_microvms(
        shared_cache,
        client_factory,
        checkpointer or NoCheckpointSupport(),
        activity or UnknownActivity(),
        now=NOW,
    )


def _node(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:6]}"


def test_record_without_vm_is_cleared(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("rec")
    node = add_node(node_id)
    gone_id, exited_id = new_sandbox_id(), new_sandbox_id()
    for sandbox_id in (gone_id, exited_id):
        record_placement(
            shared_cache,
            tenant_cache,
            tenant_id=TENANT_ID,
            sandbox_id=sandbox_id,
            placement=SandboxPlacement(node_id=node_id, generation=7),
        )
    exited = node.agent.add_vm(
        sandbox_id=str(exited_id),
        tenant_id=TENANT_ID,
        attempt=1,
        state=hostagent_pb2.VM_STATE_EXITED,
    )
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=exited_id,
        placement=SandboxPlacement(node_id=node_id, generation=exited.generation),
    )

    report = _reconcile(shared_cache, client_factory)

    assert sorted(report.cleared) == sorted([str(gone_id), str(exited_id)])
    assert get_sandbox_placement(tenant_cache, gone_id) is None
    assert get_sandbox_placement(tenant_cache, exited_id) is None
    assert list_indexed_placements(shared_cache, node_id) == []
    assert node.agent.stop_calls == []


def test_vm_without_record_is_adopted_when_the_row_matches(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
) -> None:
    node_id = _node("adopt")
    node = add_node(node_id)
    sandbox = make_db_sandbox(status=SandboxStatus.RUNNING, attempt=3)
    vm = node.agent.add_vm(sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=3)
    # Placement stores the attempt's key before Create.
    set_sandbox_daemon_key(
        tenant_cache, sandbox.id, attempt=3, key=new_sandboxd_key(), ttl_seconds=60
    )

    report = _reconcile(shared_cache, client_factory)

    assert report.adopted == [str(sandbox.id)]
    assert get_sandbox_placement(tenant_cache, sandbox.id) == SandboxPlacement(
        node_id=node_id, generation=vm.generation
    )
    # The next pass sees a matching record and only refreshes it.
    again = _reconcile(shared_cache, client_factory)
    assert again.refreshed == [str(sandbox.id)] and again.adopted == []


def test_orphan_is_marked_and_never_stopped_without_checkpoint(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("orphan"))
    # Stale attempt: the row moved on to attempt 2.
    stale = make_db_sandbox(status=SandboxStatus.RUNNING, attempt=2)
    node.agent.add_vm(sandbox_id=str(stale.id), tenant_id=TENANT_ID, attempt=1)
    # No sandbox row at all.
    unknown_id = new_sandbox_id()
    node.agent.add_vm(sandbox_id=str(unknown_id), tenant_id=TENANT_ID, attempt=1)

    report = _reconcile(shared_cache, client_factory)

    assert sorted(report.orphans_marked) == sorted([str(stale.id), str(unknown_id)])
    assert report.orphans_stopped == []
    assert node.agent.stop_calls == []
    assert len(node.agent.vms) == 2
    assert get_sandbox_placement(tenant_cache, stale.id) is None

    report = _reconcile(shared_cache, client_factory, checkpointer=AlwaysSaved())
    assert sorted(report.orphans_stopped) == sorted([str(stale.id), str(unknown_id)])
    assert node.agent.vms == {}


def test_orphan_on_second_node_is_not_stopped_when_record_points_elsewhere(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
) -> None:
    home_id = _node("home")
    home = add_node(home_id)
    other = add_node(_node("other"))
    sandbox = make_db_sandbox(status=SandboxStatus.RUNNING, attempt=1)
    placed = home.agent.add_vm(
        sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=1
    )
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox.id,
        placement=SandboxPlacement(node_id=home_id, generation=placed.generation),
    )
    other.agent.add_vm(sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=1)

    report = _reconcile(shared_cache, client_factory)

    assert report.refreshed == [str(sandbox.id)]
    assert report.orphans_marked == [str(sandbox.id)]
    assert report.adopted == []
    assert other.agent.stop_calls == [] and home.agent.stop_calls == []
    assert get_sandbox_placement(tenant_cache, sandbox.id) == SandboxPlacement(
        node_id=home_id, generation=placed.generation
    )


def test_unreachable_node_keeps_its_records(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("down")
    add_node(node_id).stop()
    sandbox_id = new_sandbox_id()
    placement = SandboxPlacement(node_id=node_id, generation=9)
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        placement=placement,
    )

    report = _reconcile(shared_cache, client_factory)

    assert report.unreachable_nodes == [node_id]
    assert report.cleared == []
    assert get_sandbox_placement(tenant_cache, sandbox_id) == placement


def test_reconcile_sleeps_idle_quiet_vm_with_checkpoint(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
) -> None:
    node_id = _node("sleep")
    node = add_node(node_id)
    idle_since = NOW - timedelta(seconds=SANDBOX_FC_IDLE_TIMEOUT_SECONDS + 60)
    idle = make_db_sandbox(attempt=1, last_heartbeat=idle_since)
    fresh = make_db_sandbox(attempt=1)
    for sandbox in (idle, fresh):
        vm = node.agent.add_vm(
            sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=1
        )
        record_placement(
            shared_cache,
            tenant_cache,
            tenant_id=TENANT_ID,
            sandbox_id=sandbox.id,
            placement=SandboxPlacement(node_id=node_id, generation=vm.generation),
        )

    # Defaults (no checkpoint support, unknown activity) keep both.
    assert _reconcile(shared_cache, client_factory).slept == []
    assert len(node.agent.vms) == 2

    report = _reconcile(
        shared_cache, client_factory, checkpointer=AlwaysSaved(), activity=Quiet()
    )
    assert report.slept == [str(idle.id)]
    assert list(node.agent.vms) == [str(fresh.id)]
    assert get_sandbox_placement(tenant_cache, idle.id) is None


def test_vm_without_its_daemon_key_is_not_adopted(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
) -> None:
    node = add_node(_node("nokey"))
    sandbox = make_db_sandbox(status=SandboxStatus.RUNNING, attempt=2)
    node.agent.add_vm(sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=2)
    # A key of another attempt does not count.
    set_sandbox_daemon_key(
        tenant_cache, sandbox.id, attempt=1, key=new_sandboxd_key(), ttl_seconds=60
    )

    report = _reconcile(shared_cache, client_factory)

    assert report.adopted == []
    assert report.orphans_marked == [str(sandbox.id)]
    assert get_sandbox_placement(tenant_cache, sandbox.id) is None
    # No checkpoint support: the orphan is only marked.
    assert node.agent.stop_calls == []


def test_a_failing_vm_does_not_end_the_pass(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = add_node(_node("isolate"))
    broken, healthy = make_db_sandbox(), make_db_sandbox()
    for sandbox in (broken, healthy):
        node.agent.add_vm(sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=1)
        set_sandbox_daemon_key(
            tenant_cache, sandbox.id, attempt=1, key=new_sandboxd_key(), ttl_seconds=60
        )
    load = reconcile._load_sandbox_row

    def load_or_fail(tenant_id: str, sandbox_id: UUID) -> reconcile._SandboxRow | None:
        if sandbox_id == broken.id:
            raise RuntimeError("tenant schema is gone")
        return load(tenant_id, sandbox_id)

    monkeypatch.setattr(reconcile, "_load_sandbox_row", load_or_fail)

    report = _reconcile(shared_cache, client_factory)

    assert report.adopted == [str(healthy.id)]
    assert len(report.failed) == 1 and str(broken.id) in report.failed[0]


def test_lease_is_checked_before_every_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    make_db_sandbox: MakeSandbox,
) -> None:
    node = add_node(_node("lease"))
    for sandbox in (make_db_sandbox(), make_db_sandbox()):
        node.agent.add_vm(sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=1)
        set_sandbox_daemon_key(
            tenant_cache, sandbox.id, attempt=1, key=new_sandboxd_key(), ttl_seconds=60
        )
    checks: list[int] = []

    def check_lease() -> None:
        checks.append(1)
        # The node step and the first VM pass; the lease is lost before the
        # second VM of the same node.
        if len(checks) == 3:
            raise TimeoutError("deadline")

    with pytest.raises(TimeoutError):
        reconcile_microvms(
            shared_cache,
            client_factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            now=NOW,
            check_lease=check_lease,
        )
    assert len(checks) == 3
