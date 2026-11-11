"""Placement and admission against Redis and fake host agents (ENG-4577)."""

import base64
import random
import threading
from collections.abc import Iterator, MutableSequence
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError

from onyx.cache.interface import TTL_NO_EXPIRY, CacheBackend, CacheLock
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm import admission, configs, placement, registry
from onyx.microvm.agent_client import HostAgentErrorReason
from onyx.microvm.models import PlacedVm, RegisteredNode, VmRequest
from onyx.microvm.placement import place_sandbox_vm
from onyx.microvm.registry import (
    SandboxReservation,
    get_sandbox_placement,
    get_sandbox_reservation,
    list_indexed_placements,
    list_registered_nodes,
    reserve_sandbox,
)
from onyx.server.features.build.sandbox.models import SandboxProvisionContentionError
from onyx.server.features.microvm.api import (
    SandboxNodeSigningKeyRegistration,
    register_sandbox_node_signing_key,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
)


def _request(sandbox_id: UUID, attempt: int = 1) -> VmRequest:
    return VmRequest(
        tenant_id=TENANT_ID, sandbox_id=sandbox_id, attempt=attempt, template="tpl-1"
    )


def _node(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:6]}"


def test_picks_most_free_memory_and_writes_record(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    small = add_node(_node("small"), FakeHostAgent(mem_available_mib=4096))
    big_id = _node("big")
    big = add_node(big_id, FakeHostAgent(mem_available_mib=32_768))
    mid = add_node(_node("mid"), FakeHostAgent(mem_available_mib=8192))
    sandbox_id = new_sandbox_id()

    placed = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(sandbox_id)
    )

    assert placed.node.node_id == big_id
    assert placed.created
    assert big.agent.create_calls == 1
    assert small.agent.create_calls == mid.agent.create_calls == 0
    # mem_mib and vcpus come from the node's template.
    assert placed.vm.mem_mib == 2048 and placed.vm.vcpus == 2
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None
    assert (record.node_id, record.attempt, record.generation) == (
        big_id,
        1,
        placed.vm.generation,
    )
    assert [p.sandbox_id for p in list_indexed_placements(shared_cache, big_id)] == [
        sandbox_id
    ]
    # Durable: the record and the daemon key have no TTL, and the
    # reservation ended with the Create.
    assert (
        tenant_cache.ttl(registry._PLACEMENT_PREFIX + str(sandbox_id)) == TTL_NO_EXPIRY
    )
    assert (
        tenant_cache.ttl(registry._DAEMON_KEY_PREFIX + str(sandbox_id)) == TTL_NO_EXPIRY
    )
    assert get_sandbox_reservation(tenant_cache, sandbox_id) is None


@pytest.mark.parametrize(
    "reason",
    [HostAgentErrorReason.CAPACITY_VM_SLOTS, HostAgentErrorReason.NODE_DRAINING],
)
def test_refusal_moves_to_next_node(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    reason: HostAgentErrorReason,
) -> None:
    refusing = add_node(_node("refuses"), FakeHostAgent(mem_available_mib=32_768))
    refusing.agent.refuse_create = reason
    second_id = _node("second")
    add_node(second_id, FakeHostAgent(mem_available_mib=8192))

    placed = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(new_sandbox_id())
    )

    assert refusing.agent.create_calls == 1
    assert placed.node.node_id == second_id


def test_one_vm_per_sandbox(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    a = add_node(_node("a"), FakeHostAgent(mem_available_mib=32_768))
    b = add_node(_node("b"), FakeHostAgent(mem_available_mib=32_000))
    sandbox_id = new_sandbox_id()

    first = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(sandbox_id)
    )
    # Node b now has more free memory, but the sandbox keeps its VM.
    again = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(sandbox_id)
    )
    assert not again.created
    assert again.vm.generation == first.vm.generation
    assert a.agent.create_calls + b.agent.create_calls == 1

    with pytest.raises(OnyxError) as exc:
        place_sandbox_vm(
            shared_cache, tenant_cache, client_factory, _request(sandbox_id, attempt=2)
        )
    assert exc.value.error_code is OnyxErrorCode.CONFLICT
    assert a.agent.create_calls + b.agent.create_calls == 1


def test_capacity_error_has_real_reason(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    with pytest.raises(OnyxError) as exc:
        place_sandbox_vm(
            shared_cache, tenant_cache, client_factory, _request(new_sandbox_id())
        )
    assert exc.value.error_code is OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
    assert exc.value.extra == {"reason": "NO_NODES", "nodes": {}}

    full_a, full_b = _node("full"), _node("full")
    add_node(full_a, FakeHostAgent(mem_available_mib=1024))
    add_node(full_b, FakeHostAgent(mem_available_mib=512))
    gone_id = _node("gone")
    add_node(gone_id).stop()

    with pytest.raises(OnyxError) as exc:
        place_sandbox_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            _request(new_sandbox_id()),
            rng=random.Random(0),
        )
    assert exc.value.error_code is OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
    assert exc.value.status_code == 503
    assert exc.value.extra == {
        "reason": "CAPACITY_MEMORY",
        "nodes": {
            full_a: "CAPACITY_MEMORY",
            full_b: "CAPACITY_MEMORY",
            gone_id: "NODE_UNREACHABLE",
        },
    }


def test_refusal_reason_from_agent(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node_id = _node("disk")
    add_node(node_id).agent.refuse_create = HostAgentErrorReason.CAPACITY_DISK

    with pytest.raises(OnyxError) as exc:
        place_sandbox_vm(
            shared_cache, tenant_cache, client_factory, _request(new_sandbox_id())
        )
    assert exc.value.extra == {
        "reason": "CAPACITY_DISK",
        "nodes": {node_id: "CAPACITY_DISK"},
    }


def test_unknown_create_outcome_pins_the_next_wake_to_that_node(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    first_id = _node("lost")
    first = add_node(first_id, FakeHostAgent(mem_available_mib=32_768))
    second = add_node(_node("other"), FakeHostAgent(mem_available_mib=8192))
    first.agent.lost_create_answers = 1
    sandbox_id = new_sandbox_id()

    with pytest.raises(OnyxError) as exc:
        place_sandbox_vm(
            shared_cache, tenant_cache, client_factory, _request(sandbox_id)
        )
    assert exc.value.extra is not None
    assert exc.value.extra["reason"] == "NODE_UNREACHABLE"

    # The VM started on the first node. The second node now ranks higher, but
    # the next wake must return the first node's VM, not start a second one.
    second.agent.mem_available_mib = 64_000
    placed = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(sandbox_id)
    )
    assert placed.node.node_id == first_id and not placed.created
    assert second.agent.create_calls == 0
    assert len(first.agent.vms) == 1
    assert get_sandbox_reservation(tenant_cache, sandbox_id) is None


@pytest.mark.parametrize(
    "reason,code",
    [
        (HostAgentErrorReason.INTERNAL, OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE),
        (HostAgentErrorReason.SANDBOX_IN_DOUBT, OnyxErrorCode.CONFLICT),
    ],
)
def test_unknown_create_failure_keeps_the_reservation(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
    reason: HostAgentErrorReason,
    code: OnyxErrorCode,
) -> None:
    failing_id = _node("failing")
    failing = add_node(failing_id, FakeHostAgent(mem_available_mib=32_768))
    failing.agent.refuse_create = reason
    other = add_node(_node("other"), FakeHostAgent(mem_available_mib=8192))
    sandbox_id = new_sandbox_id()

    with pytest.raises(OnyxError) as exc:
        place_sandbox_vm(
            shared_cache, tenant_cache, client_factory, _request(sandbox_id)
        )

    assert exc.value.error_code == code
    assert exc.value.extra is not None and exc.value.extra["reason"] == reason.value
    assert other.agent.create_calls == 0
    found = get_sandbox_reservation(tenant_cache, sandbox_id)
    assert found is not None
    assert (found[0].node_id, found[0].attempt) == (failing_id, 1)
    assert tenant_cache.ttl(registry._RESERVATION_PREFIX + str(sandbox_id)) == (
        TTL_NO_EXPIRY
    )


def test_reserved_node_refusal_moves_to_next_node(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    pinned_id = _node("pinned")
    refusing = add_node(pinned_id, FakeHostAgent(mem_available_mib=32_768))
    refusing.agent.refuse_create = HostAgentErrorReason.CAPACITY_VM_SLOTS
    other_id = _node("other")
    add_node(other_id, FakeHostAgent(mem_available_mib=8192))
    sandbox_id = new_sandbox_id()
    # A leftover reservation, as a Create with no known outcome leaves it.
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=1, node_id=pinned_id, owner="crashed"),
        replaces=None,
    )

    placed = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(sandbox_id)
    )

    assert refusing.agent.create_calls == 1
    assert placed.node.node_id == other_id and placed.vm.attempt == 1
    assert get_sandbox_reservation(tenant_cache, sandbox_id) is None


def test_reservation_on_a_dead_node_is_taken_over_with_the_next_attempt(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    live_id = _node("live")
    live = add_node(live_id)
    sandbox_id = new_sandbox_id()
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=3, node_id=_node("dead"), owner="crashed"),
        replaces=None,
    )

    placed = place_sandbox_vm(
        shared_cache, tenant_cache, client_factory, _request(sandbox_id)
    )

    # Attempt 3 may still run on the dead node: the new VM is attempt 4.
    assert placed.node.node_id == live_id and placed.vm.attempt == 4
    assert live.agent.create_requests[0][1] == 4
    record = get_sandbox_placement(tenant_cache, sandbox_id)
    assert record is not None and record.attempt == 4


def test_concurrent_wakes_create_one_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    a = add_node(_node("a"), FakeHostAgent(mem_available_mib=32_768))
    b = add_node(_node("b"), FakeHostAgent(mem_available_mib=32_000))
    a.agent.create_delay_seconds = b.agent.create_delay_seconds = 0.3
    sandbox_id = new_sandbox_id()
    results: list[PlacedVm] = []
    errors: list[Exception] = []

    def wake() -> None:
        try:
            results.append(
                place_sandbox_vm(
                    shared_cache, tenant_cache, client_factory, _request(sandbox_id)
                )
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=wake) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(a.agent.vms) + len(b.agent.vms) == 1
    assert len({r.vm.generation for r in results}) == 1
    assert sorted(r.created for r in results) == [False, True]


@contextmanager
def _no_lock(*_args: object, **_kwargs: object) -> Iterator[CacheLock]:
    yield MagicMock(spec=CacheLock)


class _NodeOrder(random.Random):
    """Ranks equal nodes by id, ascending or descending, so concurrent wakes
    would pick different nodes."""

    def __init__(self, descending: bool) -> None:
        super().__init__(0)
        self.descending = descending

    def shuffle(self, x: MutableSequence[Any]) -> None:
        x[:] = sorted(x, key=lambda n: n.node_id, reverse=self.descending)


def test_reservation_alone_keeps_one_vm_without_the_lock(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    """The placement lock only makes the second wake wait. Without it (an
    expired lease), the reservation still allows one VM per sandbox."""
    a = add_node(_node("a"), FakeHostAgent(mem_available_mib=32_768))
    b = add_node(_node("b"), FakeHostAgent(mem_available_mib=32_768))
    a.agent.create_delay_seconds = b.agent.create_delay_seconds = 0.3
    sandbox_id = new_sandbox_id()
    results: list[PlacedVm] = []
    errors: list[Exception] = []
    start = threading.Barrier(3)

    def wake(descending: bool) -> None:
        start.wait()
        try:
            results.append(
                place_sandbox_vm(
                    shared_cache,
                    tenant_cache,
                    client_factory,
                    _request(sandbox_id),
                    rng=_NodeOrder(descending),
                )
            )
        except Exception as e:
            errors.append(e)

    with patch.object(placement, "sandbox_placement_lock", _no_lock):
        threads = [threading.Thread(target=wake, args=(i % 2 == 1,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(a.agent.vms) + len(b.agent.vms) == 1
    assert results, errors
    assert len({r.vm.generation for r in results}) == 1
    assert all(isinstance(e, SandboxProvisionContentionError) for e in errors)


def test_bad_number_settings_use_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_FC_TEST_NUMBER", "3O")
    assert configs._fc_env_int("SANDBOX_FC_TEST_NUMBER", 5, minimum=1) == 5
    assert configs._fc_env_float("SANDBOX_FC_TEST_NUMBER", 2.5) == 2.5
    monkeypatch.setenv("SANDBOX_FC_TEST_NUMBER", "-4")
    assert configs._fc_env_int("SANDBOX_FC_TEST_NUMBER", 5, minimum=0) == 0
    assert configs._fc_env_float("SANDBOX_FC_TEST_NUMBER", 10.0, minimum=1.0) == 1.0
    monkeypatch.delenv("SANDBOX_FC_TEST_NUMBER")
    assert configs._fc_env_int("SANDBOX_FC_TEST_NUMBER", 5) == 5


def test_scheduled_run_jitter_only_with_firecracker() -> None:
    rng = random.Random(1)
    assert admission.scheduled_run_jitter_seconds(rng) == 0.0
    with patch.object(admission, "FIRECRACKER_ENABLED", True):
        delays = [admission.scheduled_run_jitter_seconds(rng) for _ in range(20)]
    assert all(
        0 <= d <= admission.SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS for d in delays
    )
    assert len(set(delays)) > 1


def test_registration_with_agent_address_makes_node_placeable(
    shared_cache: CacheBackend,
) -> None:
    raw = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    node_id = _node("reg")
    try:
        register_sandbox_node_signing_key(
            SandboxNodeSigningKeyRegistration(
                node_id=node_id,
                key_id=f"{node_id}-1",
                public_key=base64.b64encode(raw).decode(),
                agent_address="10.0.3.7:7443",
            )
        )
        assert list_registered_nodes(shared_cache) == [
            RegisteredNode(node_id=node_id, address="10.0.3.7:7443")
        ]
        with pytest.raises(ValidationError):
            SandboxNodeSigningKeyRegistration(
                node_id=node_id,
                key_id=f"{node_id}-2",
                public_key=base64.b64encode(raw).decode(),
                agent_address="http://10.0.3.7:7443/",
            )
    finally:
        shared_cache.delete(registry._KEY_PREFIX + f"{node_id}-1")
        shared_cache.delete(registry._NODE_KIDS_PREFIX + node_id)
        shared_cache.delete(registry._NODE_ADDRESS_PREFIX + node_id)
