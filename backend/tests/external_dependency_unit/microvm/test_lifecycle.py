"""VM lifecycle against Redis and fake host agents (ENG-4576): wake on the
first tool call, idle sleep only when nothing runs, and stop only after a
saved checkpoint and a fresh liveness check."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from onyx.cache.interface import CacheBackend
from onyx.microvm.agent_client import AgentVm
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    VmStopOutcome,
    refresh_sandbox_placement,
    sleep_idle_sandbox_vm,
    wake_sandbox_vm,
)
from onyx.microvm.placement import VmRequest
from onyx.microvm.registry import SandboxPlacement, get_sandbox_placement
from tests.external_dependency_unit.microvm.conftest import TENANT_ID, AddNode
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
)

NOW = datetime.now(timezone.utc)
IDLE = NOW - timedelta(seconds=SANDBOX_FC_IDLE_TIMEOUT_SECONDS + 60)
ACTIVE = NOW - timedelta(seconds=SANDBOX_FC_IDLE_TIMEOUT_SECONDS - 60)


class SavedCheckpoint(SandboxCheckpointer):
    def __init__(self, on_save: FakeHostAgent | None = None) -> None:
        self.saved: list[int] = []
        # Simulates the VM exiting while the checkpoint runs.
        self.drop_vm_from = on_save

    def save_checkpoint(self, *, tenant_id: str, sandbox_id: UUID, vm: AgentVm) -> bool:  # noqa: ARG002
        self.saved.append(vm.generation)
        if self.drop_vm_from is not None:
            self.drop_vm_from.vms.pop(str(sandbox_id))
        return True


class Activity(SandboxActivityProbe):
    def __init__(self, busy: bool) -> None:
        self.busy = busy

    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:  # noqa: ARG002
        return self.busy


def _wake(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox_id: UUID,
) -> int:
    placed = wake_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        VmRequest(
            tenant_id=TENANT_ID, sandbox_id=sandbox_id, attempt=1, template="tpl-1"
        ),
    )
    return placed.vm.generation


def _sleep(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox_id: UUID,
    *,
    checkpointer: SandboxCheckpointer,
    busy: bool,
    last_heartbeat: datetime,
) -> VmStopOutcome:
    return sleep_idle_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        checkpointer,
        Activity(busy),
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        last_heartbeat=last_heartbeat,
        created_at=last_heartbeat,
        now=NOW,
    )


def test_wake_starts_vm_only_on_first_call(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
) -> None:
    node = add_node(f"wake-{uuid4().hex[:6]}")
    sandbox_id = uuid4()
    assert node.agent.create_calls == 0
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None

    generation = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    assert node.agent.create_calls == 1
    assert _wake(shared_cache, tenant_cache, client_factory, sandbox_id) == generation
    assert node.agent.create_calls == 1

    # The VM exited: the next tool call starts a new instance.
    node.agent.vms.pop(str(sandbox_id))
    assert _wake(shared_cache, tenant_cache, client_factory, sandbox_id) != generation
    assert node.agent.create_calls == 2


def test_heartbeat_refreshes_only_the_current_instance(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
) -> None:
    node_id = f"hb-{uuid4().hex[:6]}"
    add_node(node_id)
    sandbox_id = uuid4()
    generation = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    current = SandboxPlacement(node_id=node_id, generation=generation)
    stale = SandboxPlacement(node_id=node_id, generation=generation - 1)

    assert refresh_sandbox_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        placement=current,
    )
    assert not refresh_sandbox_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        placement=stale,
    )
    assert get_sandbox_placement(tenant_cache, sandbox_id) == current


def test_idle_sleep_rules(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
) -> None:
    node = add_node(f"idle-{uuid4().hex[:6]}")
    sandbox_id = uuid4()
    generation = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    saver = SavedCheckpoint()

    def sleep(
        checkpointer: SandboxCheckpointer, busy: bool, heartbeat: datetime
    ) -> VmStopOutcome:
        return _sleep(
            shared_cache,
            tenant_cache,
            client_factory,
            sandbox_id,
            checkpointer=checkpointer,
            busy=busy,
            last_heartbeat=heartbeat,
        )

    # P4: not idle for the timeout yet.
    assert sleep(saver, False, ACTIVE) is VmStopOutcome.NOT_IDLE
    # P7: idle, but something runs.
    assert sleep(saver, True, IDLE) is VmStopOutcome.KEPT_BUSY
    # Idle and quiet, but no checkpoint support: keep the VM.
    assert sleep(NoCheckpointSupport(), False, IDLE) is VmStopOutcome.KEPT_NO_CHECKPOINT
    assert node.agent.stop_calls == []
    assert saver.saved == []

    assert sleep(saver, False, IDLE) is VmStopOutcome.STOPPED
    assert saver.saved == [generation]
    assert node.agent.stop_calls == [(str(sandbox_id), 1, generation)]
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None


def test_stop_rechecks_liveness_after_checkpoint(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
) -> None:
    node = add_node(f"recheck-{uuid4().hex[:6]}")
    sandbox_id = uuid4()
    _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    outcome = _sleep(
        shared_cache,
        tenant_cache,
        client_factory,
        sandbox_id,
        checkpointer=SavedCheckpoint(on_save=node.agent),
        busy=False,
        last_heartbeat=IDLE,
    )

    assert outcome is VmStopOutcome.ALREADY_GONE
    assert node.agent.stop_calls == []
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None
