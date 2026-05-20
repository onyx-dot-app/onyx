from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from mitmproxy import http

from onyx.sandbox_proxy.addons.passthrough import PassthroughAddon
from onyx.sandbox_proxy.identity import SessionContext


def _make_flow(src_ip: str | None, host: str = "api.slack.com") -> http.HTTPFlow:
    """Stand-in for `mitmproxy.http.HTTPFlow`. Mirrors only the fields
    the addon reads (peername, request.host/path, metadata). Cast to
    HTTPFlow so the type system trusts the duck-typed surface."""
    peername = (src_ip, 12345) if src_ip is not None else None
    return cast(
        http.HTTPFlow,
        SimpleNamespace(
            client_conn=SimpleNamespace(peername=peername),
            request=SimpleNamespace(host=host, path="/api/whatever"),
            metadata={},
        ),
    )


def _make_session_context(tenant_id: str = "public") -> SessionContext:
    return SessionContext(
        session_id=uuid4(),
        user_id=uuid4(),
        sandbox_id=uuid4(),
        tenant_id=tenant_id,
        sandbox_name="sandbox-xxxx",
        sandbox_ip="10.0.0.1",
    )


class _StubResolver:
    def __init__(self, return_value: SessionContext | None) -> None:
        self.return_value = return_value
        self.calls: list[str] = []

    def resolve(self, src_ip: str) -> SessionContext | None:
        self.calls.append(src_ip)
        return self.return_value


class _RaisingResolver:
    def resolve(self, src_ip: str) -> SessionContext | None:  # noqa: ARG002
        raise RuntimeError("simulated DB blip")


def test_request_attaches_session_context_on_identified_flow() -> None:
    ctx = _make_session_context()
    flow = _make_flow("10.0.0.1")

    PassthroughAddon(identity=_StubResolver(ctx)).request(flow)

    assert flow.metadata[PassthroughAddon.METADATA_KEY] is ctx


def test_request_does_not_attach_on_unidentified_flow() -> None:
    flow = _make_flow("10.0.0.1")

    PassthroughAddon(identity=_StubResolver(None)).request(flow)

    assert PassthroughAddon.METADATA_KEY not in flow.metadata


def test_request_forwards_without_context_when_resolver_raises() -> None:
    # The addon swallows DB-side errors so a transient outage doesn't
    # take down sandbox egress.
    flow = _make_flow("10.0.0.1")

    PassthroughAddon(identity=_RaisingResolver()).request(flow)

    assert PassthroughAddon.METADATA_KEY not in flow.metadata


def test_request_handles_missing_peername() -> None:
    resolver = _StubResolver(_make_session_context())
    flow = _make_flow(None)

    PassthroughAddon(identity=resolver).request(flow)

    assert resolver.calls == []
    assert PassthroughAddon.METADATA_KEY not in flow.metadata


def test_request_handles_non_string_peer_addr() -> None:
    # peer[0] should be a str, but a misbehaving transport could return
    # bytes/None. The addon must refuse to look up a non-string IP.
    resolver = _StubResolver(_make_session_context())
    flow = cast(
        http.HTTPFlow,
        SimpleNamespace(
            client_conn=SimpleNamespace(peername=(b"10.0.0.1", 12345)),
            request=SimpleNamespace(host="x", path="/"),
            metadata={},
        ),
    )

    PassthroughAddon(identity=resolver).request(flow)

    assert resolver.calls == []
