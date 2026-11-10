"""Node state reports: the agent pushes its VM list and the api_server
reconciles that node (`POST /microvm/node/state`), against Postgres, Redis and
fake host agents."""

import hashlib
import json
import threading
import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.cache.interface import CacheBackend
from onyx.db.enums import SandboxStatus
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.microvm import node_report, registry
from onyx.microvm.agent_client import new_sandboxd_key
from onyx.microvm.models import (
    NODE_REPORT_MAX_BODY_BYTES,
    NODE_REPORT_MAX_VMS,
    AgentVm,
    NodeStateReport,
    ReconcileReport,
    ReportedVm,
    VmState,
)
from onyx.microvm.node_report import NODE_REPORT_AUDIENCE, reconcile_node_report
from onyx.microvm.placement import record_placement
from onyx.microvm.registry import (
    SandboxPlacement,
    get_sandbox_placement,
    node_report_lease,
    register_node_signing_key,
    set_sandbox_daemon_key,
)
from onyx.server.auth_check import check_router_auth
from onyx.server.features.build.configs import SandboxRuntime
from onyx.server.features.microvm import api as microvm_api
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
    MakeSandbox,
    NewSandboxId,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    InsecureClientFactory,
    RunningFakeAgent,
)

PATH = microvm_api.SANDBOX_NODE_STATE_REPORT_PATH


class Node:
    def __init__(self, node_id: str, running: RunningFakeAgent) -> None:
        self.node_id = node_id
        self.key_id = f"{node_id}-1"
        self.private_key = Ed25519PrivateKey.generate()
        self.running = running


@pytest.fixture
def api(
    client_factory: InsecureClientFactory, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(microvm_api, "_node_report_agents", client_factory)
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(microvm_api.router)
    check_router_auth(app)
    return TestClient(app)


@pytest.fixture
def node(shared_cache: CacheBackend, add_node: AddNode) -> Generator[Node, None, None]:
    """A fake agent with its address and signing key registered."""
    node_id = f"report-{uuid4().hex[:8]}"
    reported = Node(node_id, add_node(node_id))
    register_node_signing_key(
        shared_cache,
        node_id=node_id,
        key_id=reported.key_id,
        public_key=reported.private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ),
        rotation_overlap_seconds=60,
    )
    yield reported
    shared_cache.delete(registry._KEY_PREFIX + reported.key_id)
    shared_cache.delete(registry._NODE_KIDS_PREFIX + node_id)
    shared_cache.delete_prefix(f"{registry._NODE_REPORT_JTI_PREFIX}{node_id}:")


def _vm_json(vm: AgentVm) -> dict[str, Any]:
    return ReportedVm(**vm.model_dump()).model_dump(mode="json")


def _body(node: Node, vms: list[dict[str, Any]] | None = None) -> bytes:
    if vms is None:
        listed = InsecureClientFactory().client(node.running.address).list_vms()
        vms = [_vm_json(vm) for vm in listed]
    return json.dumps({"node_id": node.node_id, "vms": vms}).encode()


def _token(
    reporter: Node,
    body: bytes,
    /,
    *,
    private_key: Ed25519PrivateKey | None = None,
    key_id: str | None = None,
    **claims: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "node": reporter.node_id,
        "iat": now,
        "exp": now + 60,
        "jti": uuid4().hex,
        "aud": NODE_REPORT_AUDIENCE,
        "body_sha256": hashlib.sha256(body).hexdigest(),
        **claims,
    }
    return jwt.encode(
        payload,
        private_key or reporter.private_key,
        algorithm="EdDSA",
        headers={"kid": key_id or reporter.key_id},
    )


def _post(api: TestClient, body: bytes, token: str | None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return api.post(PATH, content=body, headers=headers)


def test_report_adopts_refreshes_clears_and_marks_orphans(
    api: TestClient,
    node: Node,
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    make_db_sandbox: MakeSandbox,
    new_sandbox_id: NewSandboxId,
) -> None:
    agent = node.running.agent
    # A VM whose record was lost after Create: adopt it.
    lost = make_db_sandbox(status=SandboxStatus.RUNNING, attempt=2)
    lost_vm = agent.add_vm(sandbox_id=str(lost.id), tenant_id=TENANT_ID, attempt=2)
    set_sandbox_daemon_key(
        tenant_cache, lost.id, attempt=2, key=new_sandboxd_key(), ttl_seconds=60
    )
    # A VM with a matching record: refresh it.
    placed = make_db_sandbox(attempt=1)
    placed_vm = agent.add_vm(sandbox_id=str(placed.id), tenant_id=TENANT_ID, attempt=1)
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=placed.id,
        placement=SandboxPlacement(
            node_id=node.node_id, generation=placed_vm.generation
        ),
    )
    # A record whose VM is gone: clear it.
    gone_id = new_sandbox_id()
    record_placement(
        shared_cache,
        tenant_cache,
        tenant_id=TENANT_ID,
        sandbox_id=gone_id,
        placement=SandboxPlacement(node_id=node.node_id, generation=1),
    )
    # A VM with no sandbox row: an orphan, marked but never stopped.
    orphan_id = new_sandbox_id()
    agent.add_vm(sandbox_id=str(orphan_id), tenant_id=TENANT_ID, attempt=1)

    body = _body(node)
    response = _post(api, body, _token(node, body))

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reconciled"] is True
    report = ReconcileReport(**result["report"])
    assert report.adopted == [str(lost.id)]
    assert report.refreshed == [str(placed.id)]
    assert report.cleared == [str(gone_id)]
    assert report.orphans_marked == [str(orphan_id)]
    assert report.orphans_stopped == [] and report.slept == []
    assert get_sandbox_placement(tenant_cache, lost.id) == SandboxPlacement(
        node_id=node.node_id, generation=lost_vm.generation
    )
    assert get_sandbox_placement(tenant_cache, gone_id) is None
    assert agent.stop_calls == []

    # Idempotent: the next report only refreshes.
    body = _body(node)
    again = ReconcileReport(**_post(api, body, _token(node, body)).json()["report"])
    assert sorted(again.refreshed) == sorted([str(lost.id), str(placed.id)])
    assert again.adopted == [] and again.cleared == []


def test_bad_tokens_are_rejected_and_change_nothing(
    api: TestClient,
    node: Node,
    tenant_cache: CacheBackend,
    make_db_sandbox: MakeSandbox,
) -> None:
    lost = make_db_sandbox(status=SandboxStatus.RUNNING, attempt=1)
    node.running.agent.add_vm(sandbox_id=str(lost.id), tenant_id=TENANT_ID, attempt=1)
    set_sandbox_daemon_key(
        tenant_cache, lost.id, attempt=1, key=new_sandboxd_key(), ttl_seconds=60
    )
    body = _body(node)
    now = int(time.time())
    other_node_body = _body(node).replace(node.node_id.encode(), b"someone-else", 1)

    rejected = {
        "no header": _post(api, body, None),
        "bad signature": _post(
            api, body, _token(node, body, private_key=Ed25519PrivateKey.generate())
        ),
        "unknown kid": _post(api, body, _token(node, body, key_id="nobody-1")),
        "wrong node claim": _post(api, body, _token(node, body, node="someone-else")),
        "body names another node": _post(
            api, other_node_body, _token(node, other_node_body)
        ),
        "expired": _post(api, body, _token(node, body, iat=now - 120, exp=now - 60)),
        "lifetime too long": _post(api, body, _token(node, body, exp=now + 3600)),
        "relay audience": _post(api, body, _token(node, body, aud="sandbox-proxy")),
        "other body": _post(api, body, _token(node, b"{}")),
        "bool iat": _post(api, body, _token(node, body, iat=True)),
    }

    for name, response in rejected.items():
        assert response.status_code == 401, name
    assert get_sandbox_placement(tenant_cache, lost.id) is None

    token = _token(node, body)
    assert _post(api, body, token).status_code == 200
    assert get_sandbox_placement(tenant_cache, lost.id) is not None
    # A token is single use.
    assert _post(api, body, token).status_code == 401


def test_oversized_report_is_rejected(api: TestClient, node: Node) -> None:
    huge = b" " * (NODE_REPORT_MAX_BODY_BYTES + 1)
    assert _post(api, huge, _token(node, huge)).status_code == 413

    vm = {
        "sandbox_id": str(uuid4()),
        "tenant_id": TENANT_ID,
        "attempt": 1,
        "generation": 1,
        "state": "RUNNING",
        "template": "t",
        "vcpus": 2,
        "mem_mib": 4096,
        "scratch_gib": 1,
        "pid": 1,
        "started_at": None,
    }
    too_many = _body(node, [vm] * (NODE_REPORT_MAX_VMS + 1))
    assert len(too_many) <= NODE_REPORT_MAX_BODY_BYTES
    assert _post(api, too_many, _token(node, too_many)).status_code == 400


def test_node_without_agent_address_is_refused(
    api: TestClient, node: Node, shared_cache: CacheBackend
) -> None:
    registry.clear_node_agent_address(shared_cache, node_id=node.node_id)
    body = _body(node, [])
    assert _post(api, body, _token(node, body)).status_code == 409


def test_route_is_absent_without_firecracker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx import main as onyx_main

    monkeypatch.setattr(onyx_main, "SANDBOX_RUNTIME", SandboxRuntime.POD)
    monkeypatch.setattr(onyx_main, "APP_API_PREFIX", "")
    client = TestClient(onyx_main.get_application())
    assert client.post(PATH, content=b"{}").status_code == 404


def test_reports_for_one_node_run_one_at_a_time(
    node: Node,
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = NodeStateReport(node_id=node.node_id, vms=[])
    now = datetime.now(timezone.utc)

    # Another replica holds the node's lease: skip, do not wait.
    held = node_report_lease(shared_cache, node.node_id, 30)
    assert held.acquire(blocking=False)
    try:
        skipped = reconcile_node_report(shared_cache, client_factory, report, now=now)
        assert skipped.reconciled is False
    finally:
        held.release()

    # Two concurrent reports: the second finds the first one's lease.
    entered, release = threading.Event(), threading.Event()
    real_reconcile = node_report.reconcile_node

    def slow_reconcile(*args: Any, **kwargs: Any) -> ReconcileReport:
        entered.set()
        assert release.wait(10)
        return real_reconcile(*args, **kwargs)

    monkeypatch.setattr(node_report, "reconcile_node", slow_reconcile)
    results: list[bool] = []
    first = threading.Thread(
        target=lambda: results.append(
            reconcile_node_report(
                shared_cache, client_factory, report, now=now
            ).reconciled
        )
    )
    first.start()
    assert entered.wait(10)
    second = reconcile_node_report(shared_cache, client_factory, report, now=now)
    release.set()
    first.join(10)

    assert second.reconciled is False
    assert results == [True]
    assert reconcile_node_report(
        shared_cache, client_factory, report, now=now
    ).reconciled


def test_report_vm_round_trip() -> None:
    vm = AgentVm(
        sandbox_id=str(uuid4()),
        attempt=3,
        generation=1_700_000_000_123,
        template="v1-abc",
        vcpus=2,
        mem_mib=4096,
        scratch_gib=4,
        state=VmState.RUNNING,
        pid=7,
        tenant_id=TENANT_ID,
        started_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
    )
    assert ReportedVm.model_validate_json(json.dumps(_vm_json(vm))).to_agent_vm() == vm
