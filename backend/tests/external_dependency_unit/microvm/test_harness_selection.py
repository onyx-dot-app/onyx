"""Backend choice of harness sandboxes with Firecracker and the container
backend both on (`SANDBOX_RUNTIME=auto` on Kubernetes), against Redis and
fake host agents: a live KVM node with the template takes new sandboxes, a
running sandbox keeps its backend, and a Firecracker capacity error does not
fall back to a container."""

import time
import uuid
from collections.abc import Callable, Generator
from unittest.mock import MagicMock, create_autospec
from uuid import UUID

import pytest

from onyx.cache.interface import CacheBackend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.microvm import availability, registry
from onyx.microvm.agent_client import HostAgentErrorReason
from onyx.microvm.models import HarnessBackend, NodeStateReport, SandboxToolsOffReason
from onyx.microvm.node_report import reconcile_node_report
from onyx.server.features.build.configs import SandboxRuntime
from onyx.server.features.build.sandbox import harness_factory, harness_selection
from onyx.server.features.build.sandbox.container.models import (
    ContainerRecord,
    ContainerRuntimeKind,
)
from onyx.server.features.build.sandbox.container.state import (
    clear_container_record,
    set_container_record,
)
from onyx.server.features.build.sandbox.firecracker import harness_sandbox
from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
    FirecrackerHarnessSandbox,
)
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox
from onyx.server.features.build.sandbox.harness_selection import (
    SelectingHarnessSandbox,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
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

SOURCE_TAG = "craft-fc-sel1234"
NODE_TEMPLATE = f"{SOURCE_TAG}-0123456789ab"

ReportNode = Callable[..., RunningFakeAgent]
NewRef = Callable[[], HarnessSandboxRef]


@pytest.fixture(autouse=True)
def auto_runtime(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(availability, "SANDBOX_RUNTIME", SandboxRuntime.AUTO)
    monkeypatch.setattr(availability, "SANDBOX_FC_TEMPLATE", SOURCE_TAG)
    monkeypatch.setattr(availability, "STATIC_OFF_REASON", None)
    monkeypatch.setattr(availability, "SANDBOX_FIRECRACKER_ENABLED", True)
    monkeypatch.setattr(availability, "CONTAINER_HARNESS_ENABLED", False)
    monkeypatch.setattr(availability, "SANDBOX_FC_AVAILABILITY_CACHE_SECONDS", 0.0)
    availability._availability.clear()
    availability._new_sandbox_availability.clear()
    yield
    availability._availability.clear()
    availability._new_sandbox_availability.clear()


@pytest.fixture
def report_node(
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
) -> ReportNode:
    """Register a fake agent with the template and run one report pass."""

    def report(at: int | None = None, node_id: str | None = None) -> RunningFakeAgent:
        node_id = node_id or f"sel-{uuid.uuid4().hex[:8]}"
        agent = FakeHostAgent(template=NODE_TEMPLATE)
        agent.templates[0].compatible = True
        running = add_node(node_id, agent)
        reconcile_node_report(
            shared_cache,
            client_factory,
            NodeStateReport(node_id=node_id, vms=[]),
            now=int(time.time()) if at is None else at,
        )
        return running

    return report


@pytest.fixture
def new_ref(
    tenant_cache: CacheBackend, new_sandbox_id: NewSandboxId
) -> Generator[NewRef, None, None]:
    ids: list[UUID] = []

    def new() -> HarnessSandboxRef:
        ids.append(new_sandbox_id())
        return HarnessSandboxRef(
            tenant_id=TENANT_ID, sandbox_id=ids[-1], session_id=uuid.uuid4()
        )

    yield new
    for sandbox_id in ids:
        clear_container_record(tenant_cache, sandbox_id)
        tenant_cache.delete_prefix(harness_selection._CHOICE_PREFIX + str(sandbox_id))


def _fake() -> MagicMock:
    return create_autospec(HarnessSandbox, instance=True)


def _selector(
    firecracker: HarnessSandbox | None = None, container: HarnessSandbox | None = None
) -> SelectingHarnessSandbox:
    return SelectingHarnessSandbox(
        firecracker=firecracker or _fake(),
        container=container or _fake(),
        firecracker_available=availability.firecracker_accepts_new_sandboxes,
    )


def _container_record(tenant_cache: CacheBackend, sandbox_id: UUID) -> None:
    set_container_record(
        tenant_cache,
        sandbox_id,
        ContainerRecord(
            runtime=ContainerRuntimeKind.POD,
            name=f"harness-{sandbox_id}-1",
            address="10.0.0.9:8052",
            attempt=1,
            generation=1,
            cert_pem="pem",
            last_active=int(time.time()),
        ),
    )


def _placement(tenant_cache: CacheBackend, sandbox_id: UUID, node_id: str) -> None:
    registry.write_sandbox_placement(
        tenant_cache,
        sandbox_id,
        registry.SandboxPlacement(
            node_id=node_id, attempt=1, generation=1, last_active=int(time.time())
        ),
    )


def _backend(selector: SelectingHarnessSandbox, ref: HarnessSandboxRef) -> str:
    chosen = selector.backend_for(ref)
    if chosen is selector._backends[HarnessBackend.FIRECRACKER]:
        return "firecracker"
    return "container"


@pytest.mark.usefixtures("shared_cache")
def test_without_a_kvm_node_a_new_sandbox_starts_in_a_container(
    new_ref: NewRef,
) -> None:
    firecracker, container = _fake(), _fake()
    selector = _selector(firecracker, container)
    ref = new_ref()
    selector.ensure_running(ref)
    container.ensure_running.assert_called_once_with(ref)
    firecracker.ensure_running.assert_not_called()


def test_with_a_live_kvm_node_a_new_sandbox_starts_on_firecracker(
    report_node: ReportNode, new_ref: NewRef
) -> None:
    report_node()
    firecracker, container = _fake(), _fake()
    selector = _selector(firecracker, container)
    ref = new_ref()
    list(selector.exec_command(ref, "true"))
    firecracker.exec_command.assert_called_once()
    container.exec_command.assert_not_called()


def test_a_stale_kvm_node_does_not_serve(
    report_node: ReportNode, new_ref: NewRef
) -> None:
    report_node(at=int(time.time()) - 3600)
    assert _backend(_selector(), new_ref()) == "container"


def test_a_container_sandbox_stays_in_its_container_when_a_node_comes(
    report_node: ReportNode, new_ref: NewRef, tenant_cache: CacheBackend
) -> None:
    ref = new_ref()
    selector = _selector()
    assert _backend(selector, ref) == "container"
    _container_record(tenant_cache, ref.sandbox_id)
    report_node()
    # The choice mark is gone; the container record keeps the sandbox.
    tenant_cache.delete(harness_selection._CHOICE_PREFIX + str(ref.sandbox_id))
    assert _backend(selector, ref) == "container"
    # After it stops, the next start picks again.
    clear_container_record(tenant_cache, ref.sandbox_id)
    tenant_cache.delete(harness_selection._CHOICE_PREFIX + str(ref.sandbox_id))
    assert _backend(selector, ref) == "firecracker"


def test_a_firecracker_sandbox_stays_on_firecracker_while_its_node_serves(
    report_node: ReportNode,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
    shared_cache: CacheBackend,
) -> None:
    node_id = f"sel-{uuid.uuid4().hex[:8]}"
    report_node(node_id=node_id)
    ref = new_ref()
    _placement(tenant_cache, ref.sandbox_id, node_id)
    # A cached "no node serves" answer does not move it: its own node still
    # reports.
    cached_no = SelectingHarnessSandbox(
        firecracker=_fake(), container=_fake(), firecracker_available=lambda: False
    )
    assert _backend(cached_no, ref) == "firecracker"
    # A drain blocks only new VMs: the placed sandbox keeps its node.
    registry.set_node_draining(shared_cache, node_id, True)
    assert _backend(_selector(), ref) == "firecracker"
    # Its node stopped reporting: the VM cannot serve, so the sandbox starts
    # again elsewhere, though the calls above marked Firecracker.
    registry.record_node_report(shared_cache, node_id, int(time.time()) - 3600)
    assert _backend(cached_no, ref) == "container"


def test_calls_that_see_different_node_states_agree(
    report_node: ReportNode,
    new_ref: NewRef,
    tenant_cache: CacheBackend,
    shared_cache: CacheBackend,
) -> None:
    """A call that saw the placed node down chose a container; a call that
    sees the node again must not send the same start to Firecracker."""
    node_id = f"sel-{uuid.uuid4().hex[:8]}"
    report_node(node_id=node_id)
    ref = new_ref()
    _placement(tenant_cache, ref.sandbox_id, node_id)
    registry.record_node_report(shared_cache, node_id, int(time.time()) - 3600)
    cached_no = SelectingHarnessSandbox(
        firecracker=_fake(), container=_fake(), firecracker_available=lambda: False
    )
    assert _backend(cached_no, ref) == "container"
    # Another call also sees the node down, with a different cached answer:
    # it keeps the first choice, it does not replace it.
    cached_yes = SelectingHarnessSandbox(
        firecracker=_fake(), container=_fake(), firecracker_available=lambda: True
    )
    assert _backend(cached_yes, ref) == "container"
    registry.record_node_report(shared_cache, node_id, int(time.time()))
    assert _backend(_selector(), ref) == "container"


def test_a_draining_node_takes_no_new_sandbox(
    report_node: ReportNode,
    new_ref: NewRef,
    shared_cache: CacheBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_id = f"sel-{uuid.uuid4().hex[:8]}"
    report_node(node_id=node_id)
    registry.set_node_draining(shared_cache, node_id, True)
    assert _backend(_selector(), new_ref()) == "container"
    # The tools stay: sandboxes on the draining node still serve.
    assert availability.firecracker_available()
    monkeypatch.setattr(availability, "CONTAINER_HARNESS_ENABLED", True)
    status = availability.get_sandbox_status()
    assert status.new_sandbox_backend is HarnessBackend.CONTAINER
    assert status.firecracker_off_reason is None


def test_a_placement_on_an_unregistered_node_does_not_keep_the_sandbox(
    new_ref: NewRef, tenant_cache: CacheBackend
) -> None:
    ref = new_ref()
    _placement(tenant_cache, ref.sandbox_id, f"gone-{uuid.uuid4().hex[:8]}")
    assert _backend(_selector(), ref) == "container"


def test_concurrent_first_calls_agree_on_one_backend(
    report_node: ReportNode, new_ref: NewRef
) -> None:
    ref = new_ref()
    first = _backend(_selector(), ref)
    assert first == "container"
    report_node()
    # Within the choice window, another API pod sees the node but keeps the
    # first choice.
    assert _backend(_selector(), ref) == "container"


def test_a_capacity_error_on_firecracker_does_not_fall_back(
    report_node: ReportNode,
    client_factory: InsecureClientFactory,
    new_ref: NewRef,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = report_node()
    node.agent.refuse_create = HostAgentErrorReason.CAPACITY_MEMORY
    monkeypatch.setattr(harness_sandbox, "WAKE_RETRY_SECONDS", 0.3)
    firecracker = FirecrackerHarnessSandbox(
        template=SOURCE_TAG, client_factory=client_factory
    )
    container = _fake()
    selector = _selector(firecracker, container)
    ref = new_ref()
    for _ in range(2):
        with pytest.raises(OnyxError) as exc:
            selector.ensure_running(ref)
        assert exc.value.error_code is OnyxErrorCode.SANDBOX_CAPACITY_UNAVAILABLE
    container.ensure_running.assert_not_called()


@pytest.mark.usefixtures("shared_cache")
def test_activity_calls_never_choose_and_purges_reach_both(
    new_ref: NewRef, tenant_cache: CacheBackend
) -> None:
    firecracker, container = _fake(), _fake()
    selector = _selector(firecracker, container)
    ref = new_ref()
    selector.touch(ref)
    selector.is_busy(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)
    assert (
        tenant_cache.get(harness_selection._CHOICE_PREFIX + str(ref.sandbox_id)) is None
    )
    order = MagicMock()
    order.attach_mock(firecracker.purge_sandbox, "firecracker")
    order.attach_mock(container.purge_sandbox, "container")
    selector.purge_sandbox(tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id)
    # Nothing runs: the container backend goes first.
    assert [c[0] for c in order.mock_calls] == ["container", "firecracker"]
    firecracker.purge_session.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError, match="down"):
        selector.purge_session(
            tenant_id=ref.tenant_id,
            sandbox_id=ref.sandbox_id,
            session_id=ref.session_id,
        )
    # One failed backend does not skip the other.
    container.purge_session.assert_called_once()


def test_a_purge_runs_first_on_the_backend_that_runs_the_sandbox(
    report_node: ReportNode, new_ref: NewRef, tenant_cache: CacheBackend
) -> None:
    """That backend deletes the live session directory and cancels commands
    before the shared records go."""
    node_id = f"sel-{uuid.uuid4().hex[:8]}"
    report_node(node_id=node_id)
    firecracker, container = _fake(), _fake()
    order = MagicMock()
    order.attach_mock(firecracker.purge_session, "firecracker")
    order.attach_mock(container.purge_session, "container")
    selector = _selector(firecracker, container)
    ref = new_ref()
    _placement(tenant_cache, ref.sandbox_id, node_id)
    selector.purge_session(
        tenant_id=ref.tenant_id, sandbox_id=ref.sandbox_id, session_id=ref.session_id
    )
    assert [c[0] for c in order.mock_calls] == ["firecracker", "container"]


@pytest.mark.parametrize(
    "firecracker, container, expected",
    [
        (True, True, SelectingHarnessSandbox),
        (True, False, FirecrackerHarnessSandbox),
        (False, True, "container"),
        (False, False, None),
    ],
)
def test_the_factory_follows_the_enabled_backends(
    monkeypatch: pytest.MonkeyPatch,
    client_factory: InsecureClientFactory,
    firecracker: bool,
    container: bool,
    expected: type | str | None,
) -> None:
    fc_instance = FirecrackerHarnessSandbox(
        template=SOURCE_TAG, client_factory=client_factory
    )
    container_instance = _fake()
    monkeypatch.setattr(harness_factory, "HARNESS_SANDBOX_ENABLED", firecracker)
    monkeypatch.setattr(harness_factory, "CONTAINER_HARNESS_ENABLED", container)
    monkeypatch.setattr(harness_factory, "_instance", fc_instance)
    monkeypatch.setattr(harness_factory, "_container_instance", container_instance)
    monkeypatch.setattr(harness_factory, "_selecting_instance", None)
    if expected is None:
        with pytest.raises(harness_factory.HarnessSandboxUnavailableError):
            harness_factory.get_harness_sandbox()
    elif expected == "container":
        assert harness_factory.get_harness_sandbox() is container_instance
    else:
        assert isinstance(expected, type)
        assert isinstance(harness_factory.get_harness_sandbox(), expected)


@pytest.mark.usefixtures("shared_cache")
def test_the_container_backend_offers_tools_without_a_kvm_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not availability.sandbox_tools_available()
    status = availability.get_sandbox_status()
    assert status.new_sandbox_backend is None
    assert status.tools_off_reason is SandboxToolsOffReason.NO_REGISTERED_NODE

    monkeypatch.setattr(availability, "CONTAINER_HARNESS_ENABLED", True)
    assert availability.sandbox_tools_available()
    status = availability.get_sandbox_status()
    assert status.tools_offered
    assert status.tools_off_reason is None
    assert status.container_backend
    assert status.new_sandbox_backend is HarnessBackend.CONTAINER
    assert status.firecracker_off_reason is SandboxToolsOffReason.NO_REGISTERED_NODE


def test_a_live_node_takes_new_sandboxes_in_the_status(
    report_node: ReportNode, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(availability, "CONTAINER_HARNESS_ENABLED", True)
    report_node()
    status = availability.get_sandbox_status()
    assert status.new_sandbox_backend is HarnessBackend.FIRECRACKER
    assert status.firecracker_off_reason is None


@pytest.mark.usefixtures("shared_cache")
def test_compose_auto_uses_only_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    """`auto` with SANDBOX_BACKEND=docker: Firecracker is off by configuration."""
    monkeypatch.setattr(availability, "SANDBOX_FIRECRACKER_ENABLED", False)
    monkeypatch.setattr(
        availability,
        "STATIC_OFF_REASON",
        SandboxToolsOffReason.RUNTIME_WITHOUT_FIRECRACKER,
    )
    monkeypatch.setattr(availability, "CONTAINER_HARNESS_ENABLED", True)
    assert not availability.firecracker_available()
    assert availability.sandbox_tools_available()
    status = availability.get_sandbox_status()
    assert status.nodes == []
    assert status.new_sandbox_backend is HarnessBackend.CONTAINER
