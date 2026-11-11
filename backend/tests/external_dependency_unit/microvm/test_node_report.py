"""Node state reports: the agent pushes its VMs and its ended list, and the
api_server reconciles that node (`POST /microvm/node/state`), against Redis
and fake host agents."""

import hashlib
import json
import threading
import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.cache.interface import CacheBackend
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.microvm import node_report, registry
from onyx.microvm.agent_client import (
    HostAgentClient,
    HostAgentClientFactory,
    HostAgentConfigError,
    new_sandboxd_key,
)
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
    SandboxReservation,
    get_sandbox_placement,
    get_sandbox_reservation,
    node_report_lease,
    register_node_signing_key,
    reserve_sandbox,
    set_sandbox_daemon_key,
    write_sandbox_placement,
)
from onyx.server.auth_check import check_router_auth
from onyx.server.features.build.configs import SandboxRuntime
from onyx.server.features.microvm import api as microvm_api
from tests.external_dependency_unit.microvm.conftest import (
    TENANT_ID,
    AddNode,
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


def _body(
    node: Node,
    vms: list[dict[str, Any]] | None = None,
    ended: list[dict[str, Any]] | None = None,
) -> bytes:
    if vms is None:
        listed = InsecureClientFactory().client(node.running.address).list_vms()
        vms = [_vm_json(vm) for vm in listed]
    return json.dumps(
        {"node_id": node.node_id, "vms": vms, "ended": ended or []}
    ).encode()


def _crashed_placement(
    tenant_cache: CacheBackend, sandbox_id: UUID, node_id: str, attempt: int
) -> None:
    """A reservation and a daemon key, as a placement leaves them when it
    crashes after Create."""
    reserve_sandbox(
        tenant_cache,
        sandbox_id,
        SandboxReservation(attempt=attempt, node_id=node_id, owner="crashed"),
        replaces=None,
    )
    set_sandbox_daemon_key(
        tenant_cache, sandbox_id, attempt=attempt, key=new_sandboxd_key()
    )


def _place(
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    sandbox_id: UUID,
    node_id: str,
    *,
    attempt: int = 1,
    generation: int,
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
            last_active=int(time.time()),
        ),
    )


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


def test_report_adopts_keeps_clears_and_stops_orphans(
    api: TestClient,
    node: Node,
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    new_sandbox_id: NewSandboxId,
) -> None:
    agent = node.running.agent
    # Placement crashed after Create: adopt the VM its reservation names.
    lost_id = new_sandbox_id()
    lost_vm = agent.add_vm(sandbox_id=str(lost_id), tenant_id=TENANT_ID, attempt=2)
    _crashed_placement(tenant_cache, lost_id, node.node_id, attempt=2)
    # A VM with a matching record: keep it (no write, no TTL to renew).
    placed_id = new_sandbox_id()
    placed_vm = agent.add_vm(sandbox_id=str(placed_id), tenant_id=TENANT_ID, attempt=1)
    _place(
        shared_cache,
        tenant_cache,
        placed_id,
        node.node_id,
        generation=placed_vm.generation,
    )
    # A record whose VM is gone: clear it (after the second List).
    gone_id = new_sandbox_id()
    _place(shared_cache, tenant_cache, gone_id, node.node_id, generation=1)
    # A record whose VM is in the ended list: clear it.
    ended_id = new_sandbox_id()
    _place(shared_cache, tenant_cache, ended_id, node.node_id, attempt=4, generation=8)
    # A VM of an older attempt than its record: stop it.
    stale_id = new_sandbox_id()
    stale_vm = agent.add_vm(sandbox_id=str(stale_id), tenant_id=TENANT_ID, attempt=1)
    assert write_sandbox_placement(
        tenant_cache,
        stale_id,
        SandboxPlacement(node_id="elsewhere", attempt=2, generation=1, last_active=0),
    )
    # A VM nothing knows: inside the grace period, so not stopped yet.
    unknown_id = new_sandbox_id()
    agent.add_vm(sandbox_id=str(unknown_id), tenant_id=TENANT_ID, attempt=1)

    ended = [
        {
            "sandbox_id": str(ended_id),
            "tenant_id": TENANT_ID,
            "attempt": 4,
            "generation": 8,
            "reason": "EXITED",
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }
    ]
    body = _body(node, ended=ended)
    response = _post(api, body, _token(node, body))

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reconciled"] is True
    report = ReconcileReport(**result["report"])
    assert report.adopted == [str(lost_id)]
    assert sorted(report.cleared) == sorted([str(gone_id), str(ended_id)])
    assert report.orphans_marked == [str(stale_id)]
    assert report.orphans_stopped == [str(stale_id)]
    assert report.idle == [] and report.slept == []
    lost = get_sandbox_placement(tenant_cache, lost_id)
    assert lost is not None and lost.names(node.node_id, 2, lost_vm.generation)
    assert get_sandbox_reservation(tenant_cache, lost_id) is None
    assert get_sandbox_placement(tenant_cache, gone_id) is None
    assert get_sandbox_placement(tenant_cache, ended_id) is None
    assert agent.stop_calls == [(str(stale_id), 1, stale_vm.generation)]

    # Idempotent: the next report changes nothing.
    body = _body(node, ended=ended)
    again = ReconcileReport(**_post(api, body, _token(node, body)).json()["report"])
    assert again.adopted == [] and again.cleared == [] and again.orphans_stopped == []


def test_bad_tokens_are_rejected_and_change_nothing(
    api: TestClient,
    node: Node,
    tenant_cache: CacheBackend,
    new_sandbox_id: NewSandboxId,
) -> None:
    lost_id = new_sandbox_id()
    node.running.agent.add_vm(sandbox_id=str(lost_id), tenant_id=TENANT_ID, attempt=1)
    _crashed_placement(tenant_cache, lost_id, node.node_id, attempt=1)
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
    assert get_sandbox_placement(tenant_cache, lost_id) is None

    token = _token(node, body)
    assert _post(api, body, token).status_code == 200
    assert get_sandbox_placement(tenant_cache, lost_id) is not None
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
    now = int(time.time())

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


def test_each_accepted_report_keeps_its_node_live(
    node: Node,
    shared_cache: CacheBackend,
    client_factory: InsecureClientFactory,
) -> None:
    now = int(time.time())
    timeout = registry.SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS
    registry.record_node_report(shared_cache, node.node_id, now - timeout - 1)
    assert registry.get_live_node(shared_cache, node.node_id, now) is None

    # Recorded even when another replica holds the lease.
    held = node_report_lease(shared_cache, node.node_id, 30)
    assert held.acquire(blocking=False)
    try:
        reconcile_node_report(
            shared_cache,
            client_factory,
            NodeStateReport(node_id=node.node_id, vms=[]),
            now=now,
        )
    finally:
        held.release()

    assert registry.get_live_node(shared_cache, node.node_id, now) is not None
    assert registry.get_live_node(shared_cache, node.node_id, now + timeout + 1) is None


class _NoMtlsFactory(HostAgentClientFactory):
    def client(self, address: str) -> HostAgentClient:  # noqa: ARG002
        raise HostAgentConfigError("SANDBOX_FC_AGENT_CLIENT_CERT_PATH must be set")


def test_missing_mtls_settings_end_the_report_with_one_error(
    node: Node,
    shared_cache: CacheBackend,
    tenant_cache: CacheBackend,
    new_sandbox_id: NewSandboxId,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for sandbox_id in (new_sandbox_id(), new_sandbox_id()):
        _place(shared_cache, tenant_cache, sandbox_id, node.node_id, generation=3)
    report = NodeStateReport(node_id=node.node_id, vms=[])

    with caplog.at_level("ERROR"):
        result = reconcile_node_report(
            shared_cache, _NoMtlsFactory(), report, now=int(time.time())
        )

    assert result.reconciled is False
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and "mTLS is not configured" in errors[0].getMessage()
    # The lease is free for the next report.
    lease = node_report_lease(shared_cache, node.node_id, 30)
    assert lease.acquire(blocking=False)
    lease.release()


def test_report_without_ended_list_is_accepted(api: TestClient, node: Node) -> None:
    """An agent without the ended list (older build) still reports."""
    body = json.dumps({"node_id": node.node_id, "vms": []}).encode()
    response = _post(api, body, _token(node, body))
    assert response.status_code == 200, response.text
    assert response.json()["reconciled"] is True


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
