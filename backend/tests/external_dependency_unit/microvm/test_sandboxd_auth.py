"""Guest daemon key flow and error mapping against Redis and fake host agents."""

import re
from uuid import UUID, uuid4

import grpc
import pytest

from onyx.cache.interface import CacheBackend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm.agent_client import (
    DialLimitError,
    GuestKeyRejectedError,
    GuestUnreachableError,
    HostAgentError,
    HostAgentErrorReason,
    InstanceMismatchError,
    MethodNotAllowedError,
    VmNotRunningError,
    new_sandboxd_key,
)
from onyx.microvm.daemon_client import (
    SANDBOX_ID_HEADER,
    SandboxDaemonClient,
    SandboxDaemonError,
    SandboxDaemonErrorReason,
    SandboxDaemonKeyNotSetError,
    _error_from_rpc,
)
from onyx.microvm.generated.sandboxd.v1 import sandboxd_pb2, sandboxd_pb2_grpc
from onyx.microvm.lifecycle import (
    SandboxVmUnusableError,
    initialize_sandbox_vm,
    sandbox_daemon,
    wake_sandbox_vm,
)
from onyx.microvm.placement import PlacedVm, VmRequest
from onyx.microvm.registry import (
    _DAEMON_KEY_PREFIX,
    clear_sandbox_daemon_key,
    get_sandbox_daemon_key,
    get_sandbox_placement,
)
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
    RunningFakeAgent,
)


def _node(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:6]}"


def _wake(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    sandbox_id: UUID,
    attempt: int = 1,
) -> PlacedVm:
    return wake_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        VmRequest(
            tenant_id=TENANT_ID,
            sandbox_id=sandbox_id,
            attempt=attempt,
            template="tpl-1",
        ),
    )


def test_create_sends_a_new_random_key_and_stores_it(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    caplog: pytest.LogCaptureFixture,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("key"))
    first, second = new_sandbox_id(), new_sandbox_id()

    placed = _wake(shared_cache, tenant_cache, client_factory, first)
    other = _wake(shared_cache, tenant_cache, client_factory, second)

    key = placed.sandboxd_key.get_secret_value()
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert other.sandboxd_key.get_secret_value() != key
    assert node.agent.create_requests[0] == (str(first), 1, key)
    assert get_sandbox_daemon_key(tenant_cache, first, attempt=1) == placed.sandboxd_key
    assert get_sandbox_daemon_key(tenant_cache, first, attempt=2) is None
    raw = tenant_cache.get(_DAEMON_KEY_PREFIX + str(first))
    assert raw is not None
    assert key not in caplog.text and key not in repr(placed)

    # A repeat wake returns the VM and its key without a Create.
    again = _wake(shared_cache, tenant_cache, client_factory, first)
    assert again.sandboxd_key == placed.sandboxd_key
    assert len(node.agent.create_requests) == 2


def test_guest_unreachable_retries_the_same_attempt_and_key(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("slow"))
    node.agent.guest_unreachable_creates = 2
    sandbox_id = new_sandbox_id()

    placed = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    key = placed.sandboxd_key.get_secret_value()
    assert node.agent.create_requests == [(str(sandbox_id), 1, key)] * 3
    assert placed.vm.attempt == 1
    assert get_sandbox_placement(tenant_cache, sandbox_id) is not None


def test_guest_unreachable_after_retries_does_not_try_another_node(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    first = add_node(_node("a"), FakeHostAgent(mem_available_mib=32_768))
    second = add_node(_node("b"), FakeHostAgent(mem_available_mib=8192))
    first.agent.guest_unreachable_creates = 10
    sandbox_id = new_sandbox_id()

    with pytest.raises(OnyxError) as exc:
        _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    assert exc.value.error_code is OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
    assert exc.value.extra is not None
    assert exc.value.extra["reason"] == HostAgentErrorReason.GUEST_UNREACHABLE.value
    assert second.agent.create_calls == 0
    # The VM runs on the first node; its key stays for a later retry.
    assert get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=1) is not None


def test_key_rejected_stops_the_vm_and_creates_the_next_attempt(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("rejected"))
    sandbox_id = new_sandbox_id()
    # A VM of this attempt whose daemon holds another key.
    stale = node.agent.add_vm(
        sandbox_id=str(sandbox_id), tenant_id=TENANT_ID, attempt=1, daemon_key="k" * 64
    )

    placed = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    assert node.agent.stop_calls == [(str(sandbox_id), 1, stale.generation)]
    assert placed.vm.attempt == 2 and placed.created
    first_key, second_key = (r[2] for r in node.agent.create_requests)
    assert first_key != second_key == placed.sandboxd_key.get_secret_value()
    assert get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=1) is None
    assert get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=2) is not None
    placement = get_sandbox_placement(tenant_cache, sandbox_id)
    assert placement is not None and placement.generation == placed.vm.generation


def test_lost_key_replaces_the_vm(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("lost"))
    sandbox_id = new_sandbox_id()
    placed = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    clear_sandbox_daemon_key(tenant_cache, sandbox_id)

    again = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    assert node.agent.stop_calls == [(str(sandbox_id), 1, placed.vm.generation)]
    assert again.vm.attempt == 2
    assert again.vm.generation != placed.vm.generation


def test_init_carries_the_key_and_scratch_size(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("init"))
    sandbox_id = new_sandbox_id()
    placed = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)

    result = initialize_sandbox_vm(
        shared_cache,
        tenant_cache,
        client_factory,
        placed,
        tenant_id=TENANT_ID,
        env={"A": "1"},
        session_ids=["s1"],
    )

    assert result.attached and result.relay_reset
    [(request, routed_to)] = node.agent.init_requests
    assert routed_to == str(sandbox_id)
    assert request.scratch_bytes == placed.vm.scratch_gib << 30 == 4 << 30
    assert request.generation == placed.vm.generation
    assert request.sandbox_id == str(sandbox_id)
    assert dict(request.env) == {"A": "1"} and list(request.session_ids) == ["s1"]
    assert 32 <= len(request.entropy) <= 4096
    # Health needs no key.
    health = SandboxDaemonClient(
        client_factory.client(placed.node.address).channel,
        sandbox_id=str(sandbox_id),
        sandboxd_key=new_sandboxd_key(),
    ).health()
    assert health.key_set and health.sandbox_id == str(sandbox_id)


def test_key_not_set_makes_the_vm_unusable(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("nokey"))
    sandbox_id = new_sandbox_id()
    placed = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    node.agent.daemon_keys.pop(str(sandbox_id))

    with pytest.raises(SandboxVmUnusableError) as exc:
        initialize_sandbox_vm(
            shared_cache,
            tenant_cache,
            client_factory,
            placed,
            tenant_id=TENANT_ID,
            env={},
            session_ids=[],
        )

    assert exc.value.attempt == 2
    assert isinstance(exc.value.__cause__, SandboxDaemonKeyNotSetError)
    assert node.agent.stop_calls == [(str(sandbox_id), 1, placed.vm.generation)]
    assert get_sandbox_placement(tenant_cache, sandbox_id) is None
    assert get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=1) is None
    # The next wake starts the next attempt.
    assert _wake(
        shared_cache, tenant_cache, client_factory, sandbox_id, exc.value.attempt
    ).created


def test_daemon_errors_are_typed(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
    new_sandbox_id: NewSandboxId,
) -> None:
    node = add_node(_node("errors"))
    sandbox_id = new_sandbox_id()
    placed = _wake(shared_cache, tenant_cache, client_factory, sandbox_id)
    channel = client_factory.client(placed.node.address).channel

    wrong = SandboxDaemonClient(
        channel, sandbox_id=str(sandbox_id), sandboxd_key=new_sandboxd_key()
    )
    with pytest.raises(SandboxDaemonError) as daemon_exc:
        wrong.init(generation=1, scratch_gib=4, env={}, session_ids=[])
    assert daemon_exc.value.reason is SandboxDaemonErrorReason.UNAUTHENTICATED
    assert daemon_exc.value.vm_unusable

    # The pass-through refuses SetKey; the client has no SetKey call.
    with pytest.raises(grpc.RpcError) as rpc_exc:
        sandboxd_pb2_grpc.SandboxdStub(channel).SetKey(
            sandboxd_pb2.SetKeyRequest(key="k" * 64),
            metadata=((SANDBOX_ID_HEADER, str(sandbox_id)),),
        )
    assert isinstance(_error_from_rpc(rpc_exc.value), MethodNotAllowedError)

    node.agent.vms.pop(str(sandbox_id))
    with pytest.raises(VmNotRunningError):
        sandbox_daemon(client_factory, placed).init(
            generation=placed.vm.generation, scratch_gib=4, env={}, session_ids=[]
        )


@pytest.mark.parametrize(
    ("reason", "error_type"),
    [
        (HostAgentErrorReason.GUEST_KEY_REJECTED, GuestKeyRejectedError),
        (HostAgentErrorReason.GUEST_UNREACHABLE, GuestUnreachableError),
        (HostAgentErrorReason.VM_NOT_RUNNING, VmNotRunningError),
        (HostAgentErrorReason.INSTANCE_MISMATCH, InstanceMismatchError),
        (HostAgentErrorReason.DIAL_LIMIT, DialLimitError),
        (HostAgentErrorReason.METHOD_NOT_ALLOWED, MethodNotAllowedError),
        (HostAgentErrorReason.CAPACITY_MEMORY, HostAgentError),
    ],
)
def test_agent_reasons_map_to_typed_errors(
    reason: HostAgentErrorReason,
    error_type: type[HostAgentError],
    new_sandbox_id: NewSandboxId,
) -> None:
    running = RunningFakeAgent(FakeHostAgent())
    running.agent.refuse_create = reason
    factory = InsecureClientFactory()
    try:
        with pytest.raises(HostAgentError) as exc:
            factory.client(running.address).create(
                sandbox_id=str(new_sandbox_id()),
                attempt=1,
                template="tpl-1",
                vcpus=2,
                mem_mib=2048,
                scratch_gib=4,
                tenant_id=TENANT_ID,
                sandboxd_key=new_sandboxd_key(),
            )
        assert type(exc.value) is error_type
        assert exc.value.reason is reason
    finally:
        factory.close()
        running.stop()
