"""Per-node reconcile against Postgres, Redis and fake host agents (ENG-4576).

Each pass gets the VM list that the node would report.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from onyx.cache.interface import CacheBackend
from onyx.db.enums import SandboxStatus
from onyx.microvm import reconcile
from onyx.microvm.agent_client import (
    HostAgentClient,
    HostAgentClientFactory,
    HostAgentConfigError,
    new_sandboxd_key,
)
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    UnknownActivity,
)
from onyx.microvm.models import AgentVm, ReconcileReport, RegisteredNode
from onyx.microvm.placement import record_placement
from onyx.microvm.reconcile import reconcile_node
from onyx.microvm.registry import (
    SandboxPlacement,
    get_registered_node,
    get_sandbox_placement,
    list_indexed_placements,
    list_registered_nodes,
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
    """Every registered node reports its `List` once."""
    merged = ReconcileReport()
    for node in list_registered_nodes(shared_cache):
        report = reconcile_node(
            shared_cache,
            client_factory,
            checkpointer or NoCheckpointSupport(),
            activity or UnknownActivity(),
            node=node,
            vms=client_factory.client(node.address).list_vms(),
            now=NOW,
        )
        merged.failed += report.failed
        merged.refreshed += report.refreshed
        merged.adopted += report.adopted
        merged.cleared += report.cleared
        merged.orphans_marked += report.orphans_marked
        merged.orphans_stopped += report.orphans_stopped
        merged.slept += report.slept
    return merged


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
    placement = SandboxPlacement(node_id=node_id, generation=9)
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        placement=placement,
    )
    node = get_registered_node(shared_cache, node_id)
    assert node is not None

    # The report does not list the VM, but the liveness check cannot reach
    # the agent: keep the record (its TTL ends it if the node is gone).
    report = reconcile_node(
        shared_cache,
        client_factory,
        NoCheckpointSupport(),
        UnknownActivity(),
        node=node,
        vms=[],
        now=NOW,
    )

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
    node_id = _node("lease")
    node = add_node(node_id)
    for sandbox in (make_db_sandbox(), make_db_sandbox()):
        node.agent.add_vm(sandbox_id=str(sandbox.id), tenant_id=TENANT_ID, attempt=1)
        set_sandbox_daemon_key(
            tenant_cache, sandbox.id, attempt=1, key=new_sandboxd_key(), ttl_seconds=60
        )
    checks: list[int] = []

    def check_lease() -> None:
        checks.append(1)
        # The refreshes and the first VM pass; the lease is lost before the
        # second VM.
        if len(checks) == 3:
            raise TimeoutError("deadline")

    registered = get_registered_node(shared_cache, node_id)
    assert registered is not None
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
    assert len(checks) == 3


def test_unfinished_passes_keep_every_live_record(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = _node("resume")
    node = add_node(node_id)
    sandbox_ids = sorted((new_sandbox_id() for _ in range(4)), key=str)
    for sandbox_id in sandbox_ids:
        vm = node.agent.add_vm(
            sandbox_id=str(sandbox_id), tenant_id=TENANT_ID, attempt=1
        )
        record_placement(
            shared_cache,
            tenant_cache,
            tenant_id=TENANT_ID,
            sandbox_id=sandbox_id,
            placement=SandboxPlacement(node_id=node_id, generation=vm.generation),
        )
    refreshed: list[UUID] = []
    real_refresh = reconcile.refresh_placement

    def counting_refresh(
        shared: CacheBackend,
        tenant: CacheBackend,
        *,
        tenant_id: str,
        sandbox_id: UUID,
        placement: SandboxPlacement,
    ) -> bool:
        refreshed.append(sandbox_id)
        return real_refresh(
            shared,
            tenant,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            placement=placement,
        )

    slow_steps: list[UUID] = []

    def record_sleep(
        _pass: object, _vm: AgentVm, sandbox_id: UUID, _cache: CacheBackend
    ) -> None:
        slow_steps.append(sandbox_id)

    monkeypatch.setattr(reconcile, "refresh_placement", counting_refresh)
    monkeypatch.setattr(reconcile._Pass, "maybe_sleep", record_sleep)
    registered = get_registered_node(shared_cache, node_id)
    assert registered is not None
    vms = client_factory.client(registered.address).list_vms()

    checks: list[int] = []

    def check_lease() -> None:
        checks.append(1)
        # 1: before the refreshes, 2: first VM, 3: second VM.
        if len(checks) == 3:
            raise TimeoutError("deadline")

    # Every pass runs out of time after one slow VM step.
    for _ in sandbox_ids:
        refreshed.clear()
        checks.clear()
        with pytest.raises(TimeoutError):
            reconcile_node(
                shared_cache,
                client_factory,
                NoCheckpointSupport(),
                UnknownActivity(),
                node=registered,
                vms=vms,
                now=NOW,
                check_lease=check_lease,
            )
        # Each unfinished pass still refreshes every live record.
        assert sorted(refreshed, key=str) == sandbox_ids

    # The slow step starts where the last pass stopped, so it reaches all VMs.
    assert slow_steps == sandbox_ids
    for sandbox_id in sandbox_ids:
        assert get_sandbox_placement(tenant_cache, sandbox_id) is not None

    # A finished pass starts again from the first VM.
    slow_steps.clear()
    reconcile_node(
        shared_cache,
        client_factory,
        NoCheckpointSupport(),
        UnknownActivity(),
        node=registered,
        vms=vms,
        now=NOW,
    )
    assert slow_steps == sandbox_ids
    slow_steps.clear()
    reconcile_node(
        shared_cache,
        client_factory,
        NoCheckpointSupport(),
        UnknownActivity(),
        node=registered,
        vms=vms,
        now=NOW,
    )
    assert slow_steps == sandbox_ids


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
    # Two records without a VM: each would need a second List over mTLS.
    for sandbox_id in (new_sandbox_id(), new_sandbox_id()):
        record_placement(
            shared_cache,
            tenant_cache,
            tenant_id=TENANT_ID,
            sandbox_id=sandbox_id,
            placement=SandboxPlacement(node_id=node_id, generation=3),
        )
    registered = get_registered_node(shared_cache, node_id)
    assert isinstance(registered, RegisteredNode)
    factory = _NoMtlsFactory()

    with pytest.raises(HostAgentConfigError):
        reconcile_node(
            shared_cache,
            factory,
            NoCheckpointSupport(),
            UnknownActivity(),
            node=registered,
            vms=[],
            now=NOW,
        )
    assert factory.calls == 1
    assert len(list_indexed_placements(shared_cache, node_id)) == 2
