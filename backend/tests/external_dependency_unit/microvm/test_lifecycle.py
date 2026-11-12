"""VM lifecycle against Redis and fake host agents: wake is an
idempotent ensure, idle eviction only when nothing runs, and stop only after
a saved checkpoint and a fresh liveness check."""

import time
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from onyx.cache.interface import CacheBackend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm import configs, registry
from onyx.microvm.configs import SANDBOX_FC_IDLE_TIMEOUT_SECONDS
from onyx.microvm.generated.hostagent.v1 import hostagent_pb2
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    VmStopOutcome,
    evict_idle_sandbox_vm,
    touch_sandbox_vm,
    wake_sandbox_vm,
)
from onyx.microvm.models import AgentVm, PlacedVm, VmRequest
from onyx.microvm.registry import get_sandbox_placement
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
)

NOW = int(time.time())
IDLE = NOW - SANDBOX_FC_IDLE_TIMEOUT_SECONDS - 60
ACTIVE = NOW - SANDBOX_FC_IDLE_TIMEOUT_SECONDS + 60


class SavedCheckpoint(SandboxCheckpointer):
    def __init__(self, on_save: FakeHostAgent | None = None) -> None:
        self.saved: list[int] = []
        # Simulates the VM exiting while the checkpoint runs.
        self.drop_vm_from = on_save

    def save_checkpoint(
        self,
        *,
        tenant_id: str,  # noqa: ARG002
        sandbox_id: UUID,
        vm: AgentVm,
        renew_lease: Callable[[], None],  # noqa: ARG002
    ) -> bool:
        self.saved.append(vm.generation)
        if self.drop_vm_from is not None:
            self.drop_vm_from.vms.pop(str(sandbox_id))
        return True


class Activity(SandboxActivityProbe):
    def __init__(self, busy: bool) -> None:
        self.busy = busy

    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:  # noqa: ARG002
        return self.busy


def _wake_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox_id: UUID,
) -> PlacedVm:
    return wake_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        VmRequest(
            tenant_id=TENANT_ID, sandbox_id=sandbox_id, attempt=1, template="tpl-1"
        ),
    )


def _wake(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox_id: UUID,
) -> int:
    return _wake_vm(
        shared_cache, tenant_cache, client_factory, sandbox_id
    ).vm.generation


def _sleep(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox_id: UUID,
    *,
    checkpointer: SandboxCheckpointer,
    busy: bool,
    last_active: int,
) -> VmStopOutcome:
    return evict_idle_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        checkpointer,
        Activity(busy),
        tenant_id=TENANT_ID,
        sandbox_id=sandbox_id,
        last_active=last_active,
        now=NOW,
    )


def test_wake_starts_vm_only_on_first_call(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(f"wake-{uuid4().hex[:6]}")
    sandbox_id = new_sandbox_id()
    assert node.agent.create_calls == 0
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None

    generation = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    assert node.agent.create_calls == 1
    assert _wake(shared_cache, tenant_cache, client_factory, sandbox_id) == generation
    assert node.agent.create_calls == 1

    # The VM is gone: the next tool call starts the next attempt.
    node.agent.vms.pop(str(sandbox_id))
    placed = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    assert placed.vm.generation != generation and placed.vm.attempt == 2
    assert node.agent.create_calls == 2


def test_wake_replaces_an_exited_vm_with_the_next_attempt(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(f"exit-{uuid4().hex[:6]}")
    recorded, unrecorded = new_sandbox_id(), new_sandbox_id()
    first = _wake(shared_cache, tenant_cache, client_factory, recorded)
    # The agent keeps an exited VM and returns it for a repeat Create of its
    # attempt, so placement must move to the next attempt.
    node.agent.vms[str(recorded)].state = hostagent_pb2.VM_STATE_EXITED
    exited = node.agent.add_vm(
        sandbox_id=str(unrecorded),
        tenant_id=TENANT_ID,
        attempt=1,
        state=hostagent_pb2.VM_STATE_EXITED,
    )

    for sandbox_id, old_generation in (
        (recorded, first),
        (unrecorded, exited.generation),
    ):
        placed = wake_sandbox_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            VmRequest(
                tenant_id=TENANT_ID, sandbox_id=sandbox_id, attempt=1, template="tpl-1"
            ),
        )
        assert placed.vm.attempt == 2 and placed.created
        assert placed.vm.state.is_live()
        assert (str(sandbox_id), 1, old_generation) in node.agent.stop_calls
        record = get_sandbox_placement(tenant_cache, sandbox_id)
        assert record is not None and record.names(
            placed.node.node_id, 2, placed.vm.generation
        )


def test_wake_on_a_dead_node_starts_the_next_attempt_elsewhere(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    dead_id, live_id = f"dead-{uuid4().hex[:6]}", f"live-{uuid4().hex[:6]}"
    dead = add_node(dead_id)
    sandbox_id = new_sandbox_id()
    first = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    assert first.node.node_id == dead_id
    live = add_node(live_id)
    # The registration of the first node expired: it counts as dead.
    shared_cache.delete(registry._NODE_ADDRESS_PREFIX + dead_id)

    placed = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)

    assert placed.node.node_id == live_id and placed.vm.attempt == 2
    assert live.agent.create_calls == 1
    # The old VM is not touched; its node's next report stops it as an orphan.
    assert dead.agent.stop_calls == [] and len(dead.agent.vms) == 1
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.names(live_id, 2, placed.vm.generation)


@pytest.mark.parametrize("reported_ago", [None, 30])
def test_a_node_counts_as_live_while_it_reports(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    reported_ago: int | None,
) -> None:
    node_id = f"reporting-{uuid4().hex[:6]}"
    node = add_node(node_id)
    sandbox_id = new_sandbox_id()
    first = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    add_node(f"other-{uuid4().hex[:6]}")
    # A node that never reported, or reported inside the timeout, is live.
    if reported_ago is not None:
        registry.record_node_report(
            shared_cache, node_id, int(time.time()) - reported_ago
        )

    placed = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)

    assert placed.node.node_id == node_id and not placed.created
    assert placed.vm.generation == first.vm.generation
    assert node.agent.create_calls == 1


def test_wake_on_a_node_whose_reports_stopped_starts_the_next_attempt_elsewhere(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    silent_id, live_id = f"silent-{uuid4().hex[:6]}", f"live-{uuid4().hex[:6]}"
    silent = add_node(silent_id)
    sandbox_id = new_sandbox_id()
    first = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    assert first.node.node_id == silent_id
    live = add_node(live_id)
    # Still registered and answering, but its last report is too old.
    registry.record_node_report(
        shared_cache,
        silent_id,
        int(time.time()) - configs.SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS - 1,
    )
    registry.record_node_report(shared_cache, live_id, int(time.time()))

    placed = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)

    assert placed.node.node_id == live_id and placed.vm.attempt == 2
    assert silent.agent.create_calls == 1 and silent.agent.stop_calls == []
    assert live.agent.create_calls == 1
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.names(live_id, 2, placed.vm.generation)
    assert [
        n.node_id for n in registry.list_live_nodes(shared_cache, int(time.time()))
    ] == [live_id]


def test_wake_keeps_the_record_when_its_live_node_does_not_answer(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    quiet = add_node(f"quiet-{uuid4().hex[:6]}")
    sandbox_id = new_sandbox_id()
    first = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    running = add_node(f"other-{uuid4().hex[:6]}")
    # Still registered, but its agent does not answer: its VM may still run.
    quiet.stop()

    with pytest.raises(OnyxError) as exc:
        _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    assert exc.value.error_code is OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
    assert running.agent.create_calls == 0
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.generation == first.vm.generation


def test_touch_updates_only_the_current_instance(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    add_node(f"touch-{uuid4().hex[:6]}")
    sandbox_id = new_sandbox_id()
    placed = _wake_vm(shared_cache, tenant_cache, client_factory, sandbox_id)
    tenant_cache.set(
        registry._PLACEMENT_PREFIX + str(sandbox_id),
        registry._placement_record(
            registry.SandboxPlacement(
                node_id=placed.node.node_id,
                attempt=1,
                generation=placed.vm.generation,
                last_active=IDLE,
            )
        ),
    )
    stale = placed.model_copy(
        update={"vm": placed.vm.model_copy(update={"generation": 1})}
    )

    assert not touch_sandbox_vm(tenant_cache, stale)
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.last_active == IDLE
    assert touch_sandbox_vm(tenant_cache, placed)
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.last_active >= NOW


def test_idle_sleep_rules(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(f"idle-{uuid4().hex[:6]}")
    sandbox_id = new_sandbox_id()
    generation = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    saver = SavedCheckpoint()

    def sleep(
        checkpointer: SandboxCheckpointer, busy: bool, last_active: int
    ) -> VmStopOutcome:
        return _sleep(
            shared_cache,
            tenant_cache,
            client_factory,
            sandbox_id,
            checkpointer=checkpointer,
            busy=busy,
            last_active=last_active,
        )

    # P4: not idle for the timeout yet.
    assert sleep(saver, False, ACTIVE) is VmStopOutcome.NOT_IDLE
    # P7: idle, but something runs.
    assert sleep(saver, True, IDLE) is VmStopOutcome.KEPT_BUSY
    # Idle, but no checkpoint support (until session saves): decide and keep.
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
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(f"recheck-{uuid4().hex[:6]}")
    sandbox_id = new_sandbox_id()
    _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    outcome = _sleep(
        shared_cache,
        tenant_cache,
        client_factory,
        sandbox_id,
        checkpointer=SavedCheckpoint(on_save=node.agent),
        busy=False,
        last_active=IDLE,
    )

    assert outcome is VmStopOutcome.ALREADY_GONE
    assert node.agent.stop_calls == []
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None
