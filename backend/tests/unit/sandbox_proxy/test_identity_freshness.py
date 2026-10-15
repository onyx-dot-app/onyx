from __future__ import annotations

import asyncio
import io
import json
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from kubernetes import client
from mitmproxy import connection, http
from sqlalchemy import Select
from sqlalchemy.orm import Session

from onyx.auth.constants import API_KEY_HEADER_ALTERNATIVE_NAME, API_KEY_HEADER_NAME
from onyx.cache.interface import CacheBackend
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.sandbox_proxy import server as server_mod
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.resolvers import onyx_pat as pat_mod
from onyx.sandbox_proxy.sandbox_identity import kubernetes as informer_mod
from onyx.sandbox_proxy.sandbox_identity import resolution as identity_mod
from onyx.sandbox_proxy.sandbox_identity.kubernetes import K8sInformerLookup
from onyx.sandbox_proxy.sandbox_identity.resolution import IdentityResolver

IP = "10.77.0.9"
API_URL = "https://identity-proof.example.invalid"
OLD_SANDBOX = UUID("11111111-1111-1111-1111-111111111111")
NEW_SANDBOX = UUID("22222222-2222-2222-2222-222222222222")
OLD_USER = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NEW_USER = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OLD_CANARY = "NONSECRET-old-user-proof-canary"
NEW_CANARY = "NONSECRET-new-user-proof-canary"


def _pod(sandbox_id: UUID, name: str) -> client.V1Pod:
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=name,
            labels={
                "app.kubernetes.io/component": "sandbox",
                "app.kubernetes.io/managed-by": "onyx",
                "onyx.app/sandbox-id": str(sandbox_id),
                "onyx.app/tenant-id": "identity-proof",
            },
        ),
        status=client.V1PodStatus(pod_ip=IP),
    )


OLD_POD = _pod(OLD_SANDBOX, "sandbox-old-user")
NEW_POD = _pod(NEW_SANDBOX, "sandbox-new-user")


def _listing(pods: list[client.V1Pod], revision: str) -> client.V1PodList:
    return client.V1PodList(
        metadata=client.V1ListMeta(resource_version=revision), items=pods
    )


class _NoCatalogMatch(RequestEvaluator):
    def __init__(self) -> None:
        self.users: list[UUID] = []

    def evaluate(
        self, request: http.Request, tenant_id: str, user_id: UUID
    ) -> AllMatchedActions | None:
        assert request.host == "identity-proof.example.invalid"
        assert tenant_id == "identity-proof"
        self.users.append(user_id)
        return None


class _ControlledWatch:
    def __init__(self, lookup: K8sInformerLookup) -> None:
        self.lookup = lookup
        self.entered = threading.Event()
        self.events: queue.Queue[dict[str, object] | Exception | None] = queue.Queue()
        self.applied = threading.Event()

    def stream(self, *_args: object, **kwargs: object) -> Iterator[dict[str, object]]:
        assert kwargs["resource_version"] in {"100", "200"}
        self.entered.set()
        while not self.lookup._stop_event.is_set():
            item = self.events.get(timeout=5)
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
            self.applied.set()

    def stop(self) -> None:
        return None


def _flow(client_conn: connection.Client | None = None) -> http.HTTPFlow:
    client_conn = client_conn or connection.Client(
        peername=(IP, 23456), sockname=("127.0.0.1", 8080)
    )
    result = http.HTTPFlow(
        client_conn, connection.Server(address=("identity-proof.example.invalid", 443))
    )
    result.request = http.Request.make("GET", f"{API_URL}/api/proof")
    return result


def _health(lookup: K8sInformerLookup) -> tuple[int, bytes]:
    readiness = server_mod._Readiness()
    readiness.ca_ready = True
    handler_type = server_mod._build_healthz_handler(readiness, lookup)
    handler = object.__new__(handler_type)
    handler.path = "/healthz"
    handler.wfile = io.BytesIO()
    response = MagicMock()
    handler.send_response = response
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.do_GET()
    return response.call_args.args[0], handler.wfile.getvalue()


def _make_gate(
    monkeypatch: pytest.MonkeyPatch, lookup: K8sInformerLookup
) -> tuple[GateAddon, _NoCatalogMatch]:
    owners = {OLD_SANDBOX: OLD_USER, NEW_SANDBOX: NEW_USER}
    tokens = {OLD_SANDBOX: OLD_CANARY, NEW_SANDBOX: NEW_CANARY}
    db = MagicMock(spec=Session)

    def owner_for_statement(statement: Select[tuple[UUID | None]]) -> UUID:
        params = statement.compile().params
        return owners[params["id_1"]]

    db.scalar.side_effect = owner_for_statement

    @contextmanager
    def db_factory(tenant_id: str) -> Iterator[Session]:
        assert tenant_id == "identity-proof"
        yield cast(Session, db)

    def sandbox_for_id(session: Session, sandbox_id: UUID) -> MagicMock:
        assert session is db
        row = MagicMock()
        row.encrypted_pat.get_value.return_value = tokens[sandbox_id]
        return row

    monkeypatch.setattr(identity_mod, "get_session_with_tenant", db_factory)
    monkeypatch.setattr(pat_mod, "get_session_with_tenant", db_factory)
    monkeypatch.setattr(pat_mod, "get_sandbox_by_id", sandbox_for_id)
    monkeypatch.setattr(pat_mod, "ONYX_SERVER_URL", API_URL)
    monkeypatch.setattr(
        "onyx.sandbox_proxy.addons.gate.is_destination_blocked",
        lambda *_args: False,
    )
    evaluator = _NoCatalogMatch()
    gate = GateAddon(
        identity=IdentityResolver(lookup),
        request_evaluator=evaluator,
        cache_factory=lambda _tenant_id: cast(
            CacheBackend, MagicMock(spec=CacheBackend)
        ),
        proxy_instance_id="identity-proof",
        credential_dispatcher=CredentialInjectionDispatcher(
            [pat_mod.OnyxPatResolver()]
        ),
        destination_policy=parse_destination_policy(API_URL),
    )
    return gate, evaluator


def _assert_canary(result: http.HTTPFlow, expected: str) -> None:
    assert result.response is None
    assert result.request.headers[API_KEY_HEADER_NAME] == f"Bearer {expected}"
    assert (
        result.request.headers[API_KEY_HEADER_ALTERNATIVE_NAME] == f"Bearer {expected}"
    )


def _assert_unidentified(result: http.HTTPFlow) -> None:
    assert result.response is not None
    assert result.response.status_code == 403
    assert result.response.content is not None
    assert json.loads(result.response.content)["error"] == "unidentified_sandbox"
    assert API_KEY_HEADER_NAME not in result.request.headers
    assert API_KEY_HEADER_ALTERNATIVE_NAME not in result.request.headers


@pytest.mark.parametrize(
    "watch_loss",
    [ConnectionError("controlled nonsecret watch loss"), None],
    ids=["connection-error", "clean-eof"],
)
def test_known_watch_loss_blocks_credentials_until_fresh_relist(
    monkeypatch: pytest.MonkeyPatch, watch_loss: Exception | None
) -> None:
    core = MagicMock(spec=client.CoreV1Api)
    lookup = K8sInformerLookup(core_api=core)
    lost_watch = _ControlledWatch(lookup)
    fresh_watch = _ControlledWatch(lookup)
    relist_entered = threading.Event()
    relist_release = threading.Event()

    def list_call(**_kwargs: object) -> client.V1PodList:
        if core.list_namespaced_pod.call_count == 1:
            return _listing([OLD_POD], "100")
        relist_entered.set()
        assert relist_release.wait(5), "test must release the replacement list"
        return _listing([NEW_POD], "200")

    core.list_namespaced_pod.side_effect = list_call
    monkeypatch.setattr(
        informer_mod.watch, "Watch", MagicMock(side_effect=[lost_watch, fresh_watch])
    )
    gate, evaluator = _make_gate(monkeypatch, lookup)
    lookup.start()
    try:
        assert lookup.wait_for_initial_sync(5)
        assert lost_watch.entered.wait(5)
        assert _health(lookup) == (200, b"ok\n")
        accepted = _flow()
        asyncio.run(gate.http_connect(accepted))
        assert accepted.response is None
        original_request = _flow(accepted.client_conn)
        asyncio.run(gate.request(original_request))
        _assert_canary(original_request, OLD_CANARY)

        lost_watch.events.put(watch_loss)
        assert relist_entered.wait(5)
        assert _health(lookup) == (503, b"not ready\n")
        existing_connection_request = _flow(accepted.client_conn)
        asyncio.run(gate.request(existing_connection_request))
        _assert_unidentified(existing_connection_request)
        replacement_request = _flow()
        asyncio.run(gate.request(replacement_request))
        _assert_unidentified(replacement_request)
        replacement_connect = _flow()
        asyncio.run(gate.http_connect(replacement_connect))
        _assert_unidentified(replacement_connect)
        assert lookup.lookup(IP) is None
        assert evaluator.users == [OLD_USER]

        relist_release.set()
        assert fresh_watch.entered.wait(5)
        assert _health(lookup) == (200, b"ok\n")
        refreshed = lookup.lookup(IP)
        assert refreshed is not None and refreshed.sandbox_id == NEW_SANDBOX
        fresh_request = _flow(accepted.client_conn)
        asyncio.run(gate.request(fresh_request))
        _assert_canary(fresh_request, NEW_CANARY)
        assert evaluator.users == [OLD_USER, NEW_USER]
    finally:
        relist_release.set()
        lookup.stop()
        lost_watch.events.put(None)
        fresh_watch.events.put(None)
        lookup._thread.join(timeout=5)
        assert not lookup._thread.is_alive()


def test_synced_watch_events_replace_identity_and_preserve_new_owner_on_old_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = MagicMock(spec=client.CoreV1Api)
    core.list_namespaced_pod.return_value = _listing([OLD_POD], "100")
    lookup = K8sInformerLookup(core_api=core)
    controlled_watch = _ControlledWatch(lookup)
    monkeypatch.setattr(informer_mod.watch, "Watch", lambda: controlled_watch)
    gate, evaluator = _make_gate(monkeypatch, lookup)
    lookup.start()
    try:
        assert controlled_watch.entered.wait(5)
        assert lookup.is_synced()
        before_event = _flow()
        asyncio.run(gate.request(before_event))
        _assert_canary(before_event, OLD_CANARY)
        controlled_watch.events.put({"type": "ADDED", "object": NEW_POD})
        assert controlled_watch.applied.wait(5)
        after_event = _flow()
        asyncio.run(gate.request(after_event))
        _assert_canary(after_event, NEW_CANARY)
        controlled_watch.applied.clear()
        controlled_watch.events.put({"type": "DELETED", "object": OLD_POD})
        assert controlled_watch.applied.wait(5)
        after_old_delete = _flow()
        asyncio.run(gate.request(after_old_delete))
        _assert_canary(after_old_delete, NEW_CANARY)
        assert evaluator.users == [OLD_USER, NEW_USER, NEW_USER]
    finally:
        lookup.stop()
        controlled_watch.events.put(None)
        lookup._thread.join(timeout=5)
        assert not lookup._thread.is_alive()
