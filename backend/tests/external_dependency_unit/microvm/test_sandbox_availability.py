"""Chat sandbox tools with `SANDBOX_RUNTIME=auto` follow live node reports,
and the admin sandbox status shows why, against Redis and fake host agents."""

import time
import uuid
from collections.abc import Callable, Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.auth.users import current_user
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.microvm import availability
from onyx.microvm.availability import get_sandbox_status, sandbox_tools_available
from onyx.microvm.models import NodeStateReport, SandboxToolsOffReason
from onyx.microvm.node_report import reconcile_node_report
from onyx.server.features.build.configs import SandboxRuntime
from onyx.server.features.microvm import admin_api
from tests.external_dependency_unit.microvm.conftest import AddNode
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
)

SOURCE_TAG = "craft-fc-abc1234"
# The node names its template "<tag>-<key hash[:12]>".
NODE_TEMPLATE = f"{SOURCE_TAG}-0123456789ab"

SetRuntime = Callable[..., None]


@pytest.fixture
def set_runtime(monkeypatch: pytest.MonkeyPatch) -> Generator[SetRuntime, None, None]:
    def set_(runtime: SandboxRuntime, template: str = SOURCE_TAG) -> None:
        monkeypatch.setattr(availability, "SANDBOX_RUNTIME", runtime)
        monkeypatch.setattr(availability, "SANDBOX_FC_TEMPLATE", template)
        monkeypatch.setattr(
            availability,
            "STATIC_OFF_REASON",
            SandboxToolsOffReason.RUNTIME_WITHOUT_FIRECRACKER
            if not runtime.uses_firecracker
            else None
            if template
            else SandboxToolsOffReason.TEMPLATE_NOT_CONFIGURED,
        )
        availability._availability.clear()

    monkeypatch.setattr(availability, "SANDBOX_FC_AVAILABILITY_CACHE_SECONDS", 0.0)
    yield set_
    availability._availability.clear()


ReportNode = Callable[..., str]


@pytest.fixture
def report_node(
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    add_node: AddNode,
) -> ReportNode:
    """Register a fake agent and run one report pass for it."""

    def report(template: str = NODE_TEMPLATE, at: int | None = None) -> str:
        node_id = f"avail-{uuid.uuid4().hex[:8]}"
        agent = FakeHostAgent(template=template)
        # Placement takes only templates the node built for its own key.
        agent.templates[0].compatible = True
        add_node(node_id, agent)
        reconcile_node_report(
            shared_cache,
            client_factory,
            NodeStateReport(node_id=node_id, vms=[]),
            now=int(time.time()) if at is None else at,
        )
        return node_id

    return report


@pytest.mark.usefixtures("shared_cache")
def test_auto_without_a_node_offers_no_tools(set_runtime: SetRuntime) -> None:
    set_runtime(SandboxRuntime.AUTO)
    assert not sandbox_tools_available()
    status = get_sandbox_status()
    assert not status.tools_offered
    assert status.tools_off_reason is SandboxToolsOffReason.NO_REGISTERED_NODE
    assert status.nodes == []


def test_auto_with_a_registered_node_that_never_reported_offers_no_tools(
    set_runtime: SetRuntime, add_node: AddNode
) -> None:
    set_runtime(SandboxRuntime.AUTO)
    add_node(f"avail-{uuid.uuid4().hex[:8]}", FakeHostAgent(template=NODE_TEMPLATE))
    assert not sandbox_tools_available()
    status = get_sandbox_status()
    assert status.tools_off_reason is SandboxToolsOffReason.NO_LIVE_NODE_WITH_TEMPLATE
    (node,) = status.nodes
    assert node.agent_version is None
    assert node.last_report_age_seconds is None


def test_auto_with_a_reporting_node_that_has_the_template_offers_tools(
    set_runtime: SetRuntime, report_node: ReportNode
) -> None:
    set_runtime(SandboxRuntime.AUTO)
    node_id = report_node()
    assert sandbox_tools_available()
    status = get_sandbox_status()
    assert status.tools_offered
    assert status.tools_off_reason is None
    (node,) = status.nodes
    assert node.node_id == node_id
    assert node.live
    assert node.has_template
    assert node.agent_version == "test"
    assert node.templates == [NODE_TEMPLATE]
    assert node.vm_count == 0
    assert node.max_vms == 0
    assert node.last_report_age_seconds is not None
    assert node.last_report_age_seconds <= 5


def test_auto_with_another_template_offers_no_tools(
    set_runtime: SetRuntime, report_node: ReportNode
) -> None:
    set_runtime(SandboxRuntime.AUTO)
    report_node(template="other-image-0123456789ab")
    assert not sandbox_tools_available()
    status = get_sandbox_status()
    assert status.tools_off_reason is SandboxToolsOffReason.NO_LIVE_NODE_WITH_TEMPLATE
    assert not status.nodes[0].has_template


def test_auto_with_a_stale_report_offers_no_tools(
    set_runtime: SetRuntime, report_node: ReportNode
) -> None:
    set_runtime(SandboxRuntime.AUTO)
    report_node(at=int(time.time()) - 3600)
    assert not sandbox_tools_available()
    status = get_sandbox_status()
    assert status.tools_off_reason is SandboxToolsOffReason.NO_LIVE_NODE_WITH_TEMPLATE
    (node,) = status.nodes
    assert not node.live
    assert node.has_template


def test_auto_reuses_its_answer_within_the_cache_window(
    set_runtime: SetRuntime,
    report_node: ReportNode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_runtime(SandboxRuntime.AUTO)
    monkeypatch.setattr(availability, "SANDBOX_FC_AVAILABILITY_CACHE_SECONDS", 3600.0)
    assert not sandbox_tools_available()
    report_node()
    assert not sandbox_tools_available()
    availability._availability.clear()
    assert sandbox_tools_available()


@pytest.mark.usefixtures("shared_cache")
def test_firecracker_offers_tools_without_a_node(set_runtime: SetRuntime) -> None:
    set_runtime(SandboxRuntime.FIRECRACKER)
    assert sandbox_tools_available()
    assert get_sandbox_status().tools_offered


@pytest.mark.parametrize("runtime", [SandboxRuntime.POD, SandboxRuntime.OFF])
def test_runtimes_without_firecracker_offer_no_tools(
    set_runtime: SetRuntime, report_node: ReportNode, runtime: SandboxRuntime
) -> None:
    report_node()
    set_runtime(runtime)
    assert not sandbox_tools_available()
    status = get_sandbox_status()
    assert status.tools_off_reason is SandboxToolsOffReason.RUNTIME_WITHOUT_FIRECRACKER
    assert status.nodes == []


@pytest.mark.usefixtures("shared_cache")
def test_auto_without_a_template_offers_no_tools(set_runtime: SetRuntime) -> None:
    set_runtime(SandboxRuntime.AUTO, template="")
    assert not sandbox_tools_available()
    assert (
        get_sandbox_status().tools_off_reason
        is SandboxToolsOffReason.TEMPLATE_NOT_CONFIGURED
    )


# Admin API

STATUS_URL = "/admin/sandbox/status"


@pytest.fixture
def status_api() -> Generator[tuple[TestClient, User], None, None]:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(admin_api.admin_router)
    user = User(
        id=uuid.uuid4(),
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
    )
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: None
    with TestClient(app) as browser:
        yield browser, user


def test_status_endpoint_returns_nodes_and_the_gate(
    status_api: tuple[TestClient, User],
    set_runtime: SetRuntime,
    report_node: ReportNode,
) -> None:
    browser, _ = status_api
    set_runtime(SandboxRuntime.AUTO)
    node_id = report_node()
    response = browser.get(STATUS_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["runtime"] == "auto"
    assert body["template"] == SOURCE_TAG
    assert body["tools_offered"] is True
    assert body["tools_off_reason"] is None
    assert [n["node_id"] for n in body["nodes"]] == [node_id]
    assert body["nodes"][0]["templates"] == [NODE_TEMPLATE]


def test_status_endpoint_denies_non_admins(
    status_api: tuple[TestClient, User], set_runtime: SetRuntime
) -> None:
    browser, user = status_api
    set_runtime(SandboxRuntime.AUTO)
    user.effective_permissions = []
    assert browser.get(STATUS_URL).status_code == 403


def test_status_endpoint_is_single_tenant_only(
    status_api: tuple[TestClient, User],
    set_runtime: SetRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser, _ = status_api
    set_runtime(SandboxRuntime.AUTO)
    monkeypatch.setattr(admin_api, "MULTI_TENANT", True)
    response = browser.get(STATUS_URL)
    assert response.status_code == 403
    assert response.json()["error_code"] == "SINGLE_TENANT_ONLY"
