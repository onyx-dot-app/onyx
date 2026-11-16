"""Gate handling of the relay's signed identity: binding, reuse, rejection."""

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from mitmproxy import http

from onyx.cache.interface import CacheBackend
from onyx.sandbox_proxy.addons import gate
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import parse_destination_policy
from onyx.sandbox_proxy.errors import SandboxProxyError
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox
from onyx.sandbox_proxy.sandbox_identity.signed import (
    SESSION_HINT_HEADER,
    SandboxClaims,
    SignedIdentityError,
    SignedIdentityRejection,
    SignedIdentityVerifier,
)
from tests.unit.sandbox_proxy.conftest import (
    StubResolver,
    make_flow,
    make_resolved_sandbox,
)

_GOOD = "Bearer good"
_SANDBOX_ID = UUID("0b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69")
_OWNER = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")
_RELAY_PEER = ("10.9.0.5", 40000)


class _StubVerifier(SignedIdentityVerifier):
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, token: str) -> tuple[SandboxClaims, UUID]:
        self.calls += 1
        if token != "good":
            raise SignedIdentityError(SignedIdentityRejection.BAD_SIGNATURE)
        claims = SandboxClaims(
            sandbox_id=_SANDBOX_ID,
            tenant_id="public",
            node_id="node-a",
            generation=3,
            jti=str(uuid4()),
            expires_at=0,
        )
        return claims, _OWNER


class _NoMatch(RequestEvaluator):
    def evaluate(self, request: Any, tenant_id: str, user_id: UUID) -> None:  # noqa: ARG002
        return None


def _build(resolver: StubResolver, verifier: _StubVerifier | None) -> GateAddon:
    return GateAddon(
        identity=resolver,
        request_evaluator=_NoMatch(),
        destination_policy=parse_destination_policy(""),
        cache_factory=lambda _tenant: MagicMock(spec=CacheBackend),
        proxy_instance_id="proxy-test",
        credential_dispatcher=CredentialInjectionDispatcher([]),
        signed_identity=verifier,
    )


def _assert_unidentified(flow: http.HTTPFlow) -> None:
    assert flow.response is not None
    assert flow.response.status_code == 403
    assert flow.response.content is not None
    body = json.loads(flow.response.content)
    assert body["error"] == SandboxProxyError.UNIDENTIFIED_SANDBOX.value


@pytest.fixture
def destinations(monkeypatch: pytest.MonkeyPatch) -> list[ResolvedSandbox | None]:
    """Records the `sandbox` passed to every destination check."""
    seen: list[ResolvedSandbox | None] = []

    def _resolve(*_args: Any, **kwargs: Any) -> tuple[str, ...]:
        seen.append(kwargs.get("sandbox"))
        return ("8.8.8.8",)

    monkeypatch.setattr(gate, "resolve_destination", _resolve)
    return seen


@pytest.mark.asyncio
async def test_signed_connect_binds_and_tunnel_reuses_identity(
    destinations: list[ResolvedSandbox | None],
) -> None:
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    addon = _build(resolver, _StubVerifier())
    session = str(uuid4())
    connect = make_flow(
        conn_id="c1",
        method="CONNECT",
        peername=_RELAY_PEER,
        proxy_auth=_GOOD,
        headers={SESSION_HINT_HEADER: session},
    )

    await addon.http_connect(connect)

    assert connect.response is None
    bound = addon._conn_signed_sandboxes["c1"]
    assert (bound.sandbox_id, bound.user_id) == (_SANDBOX_ID, _OWNER)
    assert destinations == [bound]
    assert addon._conn_session_tags["c1"] == session

    inner = make_flow(conn_id="c1", method="GET", peername=_RELAY_PEER)
    assert addon._resolve_sandbox(inner) == bound
    # The pod-IP lookup is never consulted for a signed connection.
    assert resolver.resolve_sandbox_calls == 0

    addon.client_disconnected(connect.client_conn)
    assert "c1" not in addon._conn_signed_sandboxes


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["Bearer forged", "Bearer", "bearer  "])
async def test_bad_signed_header_rejected_without_ip_fallback(
    destinations: list[ResolvedSandbox | None], header: str
) -> None:
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    addon = _build(resolver, _StubVerifier())
    flow = make_flow(conn_id="c1", method="CONNECT", proxy_auth=header)

    await addon.http_connect(flow)

    _assert_unidentified(flow)
    assert addon._conn_signed_sandboxes == {}
    assert resolver.resolve_sandbox_calls == 0
    assert destinations == []


@pytest.mark.asyncio
async def test_pod_runtime_ignores_signed_header_and_hint(
    destinations: list[ResolvedSandbox | None],
) -> None:
    """Without a verifier (`SANDBOX_RUNTIME=pod`) the gate behaves as before."""
    sandbox = make_resolved_sandbox()
    resolver = StubResolver(sandbox=sandbox)
    addon = _build(resolver, None)
    flow = make_flow(
        conn_id="c1",
        method="CONNECT",
        proxy_auth=_GOOD,
        headers={SESSION_HINT_HEADER: str(uuid4())},
    )

    await addon.http_connect(flow)

    assert flow.response is None
    assert resolver.resolve_sandbox_calls == 1
    assert addon._conn_signed_sandboxes == {}
    assert "c1" not in addon._conn_session_tags
    assert destinations == [None]
    assert addon._resolve_sandbox(make_flow(conn_id="c1", proxy_auth=_GOOD)) == sandbox


@pytest.mark.asyncio
async def test_plain_http_signed_connection_allows_one_request(
    destinations: list[ResolvedSandbox | None],
) -> None:
    verifier = _StubVerifier()
    addon = _build(StubResolver(sandbox=make_resolved_sandbox()), verifier)
    first = make_flow(
        conn_id="c1", method="GET", host="example.com", port=80, proxy_auth=_GOOD
    )

    await addon.request(first)

    assert first.response is None
    assert "Proxy-Authorization" not in first.request.headers
    assert destinations == [addon._conn_signed_sandboxes["c1"]]

    # The relay forces `Connection: close`; a second request on the same
    # connection is pipelining or a relay bug, even with a fresh token.
    second = make_flow(
        conn_id="c1", method="GET", host="example.com", port=80, proxy_auth=_GOOD
    )
    await addon.request(second)
    _assert_unidentified(second)
    assert verifier.calls == 1


@pytest.mark.asyncio
async def test_unsigned_connection_uses_ip_identity(
    destinations: list[ResolvedSandbox | None],
) -> None:
    sandbox = make_resolved_sandbox()
    resolver = StubResolver(sandbox=sandbox)
    verifier = _StubVerifier()
    addon = _build(resolver, verifier)
    flow = make_flow(conn_id="c1", method="CONNECT")

    await addon.http_connect(flow)

    assert flow.response is None
    assert addon._conn_signed_sandboxes == {}
    assert resolver.resolve_sandbox_calls == 1
    assert verifier.calls == 0
    assert destinations == [None]
    assert addon._resolve_sandbox(make_flow(conn_id="c1")) == sandbox


@pytest.mark.asyncio
async def test_verifier_error_fails_closed(
    destinations: list[ResolvedSandbox | None],  # noqa: ARG001
) -> None:
    class _Broken(_StubVerifier):
        def verify(self, token: str) -> tuple[SandboxClaims, UUID]:  # noqa: ARG002
            raise RuntimeError("db down")

    resolver = StubResolver(sandbox=make_resolved_sandbox())
    flow = make_flow(conn_id="c1", method="CONNECT", proxy_auth=_GOOD)

    await _build(resolver, _Broken()).http_connect(flow)

    _assert_unidentified(flow)
    assert resolver.resolve_sandbox_calls == 0


@pytest.mark.asyncio
async def test_signed_header_after_unsigned_request_rejected(
    destinations: list[ResolvedSandbox | None],  # noqa: ARG001
) -> None:
    """A connection identified by IP can never switch to a signed identity."""
    resolver = StubResolver(sandbox=make_resolved_sandbox())
    verifier = _StubVerifier()
    addon = _build(resolver, verifier)
    first = make_flow(conn_id="c1", method="GET", host="example.com", port=80)

    await addon.request(first)
    assert first.response is None

    second = make_flow(
        conn_id="c1", method="GET", host="example.com", port=80, proxy_auth=_GOOD
    )
    await addon.request(second)
    _assert_unidentified(second)
    assert verifier.calls == 0
    assert addon._conn_signed_sandboxes == {}
