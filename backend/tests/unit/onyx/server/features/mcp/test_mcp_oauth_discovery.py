import asyncio

import httpx
import pytest
from mcp.client.auth.exceptions import OAuthRegistrationError

from onyx.server.features.mcp import oauth_discovery
from onyx.server.features.mcp.models import MCPOAuthDiscoveryRequest


@pytest.mark.parametrize(
    "registration,cimd,expected",
    [
        (None, False, False),
        ("https://issuer.example/register", False, True),
        (None, True, True),
    ],
)
def test_discovery_reads_capabilities_without_registration(
    monkeypatch: pytest.MonkeyPatch,
    registration: str | None,
    cimd: bool,
    expected: bool,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert "authorization" not in request.headers
        if request.url.path == "/mcp":
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": 'Bearer resource_metadata="https://mcp.example/metadata"'
                },
            )
        if request.url.path == "/metadata":
            return httpx.Response(
                200,
                json={
                    "resource": "https://mcp.example/mcp",
                    "authorization_servers": ["https://issuer.example"],
                },
            )
        return httpx.Response(
            200,
            json={
                "issuer": "https://issuer.example",
                "authorization_endpoint": "https://issuer.example/authorize",
                "token_endpoint": "https://issuer.example/token",
                "response_types_supported": ["code"],
                "registration_endpoint": registration,
                "client_id_metadata_document_supported": cimd,
            },
        )

    monkeypatch.setattr(
        oauth_discovery,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(
        oauth_discovery.discover_oauth_capabilities("https://mcp.example/mcp")
    )
    assert result.status == "metadata_found"
    assert result.supports_automatic_registration is expected
    assert result.authorization_endpoint == "https://issuer.example/authorize"
    assert len(requests) == 3


@pytest.mark.parametrize("unreachable", [False, True])
def test_unknown_metadata_does_not_claim_registration_is_unsupported(
    monkeypatch: pytest.MonkeyPatch, unreachable: bool
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if unreachable:
            raise httpx.ConnectError("private details", request=request)
        return httpx.Response(404, text="<html>private details</html>")

    monkeypatch.setattr(
        oauth_discovery,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(
        oauth_discovery.discover_oauth_capabilities("https://mcp.example/mcp")
    )
    assert result.status == ("unreachable" if unreachable else "metadata_missing")
    assert result.supports_automatic_registration is None


def test_registration_error_is_sanitized_through_nested_task_groups() -> None:
    upstream = OAuthRegistrationError(
        "Registration failed: 404 <html>secret=private</html>"
    )
    error = oauth_discovery.oauth_setup_error(
        ExceptionGroup("transport", [ExceptionGroup("oauth", [upstream])])
    )
    assert error.extra == {"oauth_error": "client_registration_failed"}
    assert "own OAuth client" in error.detail
    assert "private" not in error.detail
    assert "html" not in error.detail


def test_discovery_checks_server_management_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError
    from onyx.server.features.mcp import api

    server = MagicMock()
    monkeypatch.setattr(api, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_: server)
    denied = MagicMock(side_effect=OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS))
    discover = AsyncMock()
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", denied)
    monkeypatch.setattr(api, "discover_oauth_capabilities", discover)
    with pytest.raises(OnyxError):
        asyncio.run(
            api.discover_admin_oauth(
                MCPOAuthDiscoveryRequest(server_id=42),
                MagicMock(),
            )
        )
    discover.assert_not_called()


@pytest.mark.parametrize(
    "metadata_kind", ["wrong_resource", "empty_servers", "invalid_json"]
)
def test_invalid_resource_metadata_never_follows_untrusted_issuer(
    monkeypatch: pytest.MonkeyPatch, metadata_kind: str
) -> None:
    requested_hosts: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.path == "/mcp":
            return httpx.Response(401)
        if "oauth-protected-resource" in request.url.path:
            if metadata_kind == "invalid_json":
                return httpx.Response(200, text="<html>not metadata</html>")
            return httpx.Response(
                200,
                json={
                    "resource": "https://other.example/mcp"
                    if metadata_kind == "wrong_resource"
                    else "https://mcp.example/mcp",
                    "authorization_servers": []
                    if metadata_kind == "empty_servers"
                    else ["https://untrusted.example"],
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        oauth_discovery,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(
        oauth_discovery.discover_oauth_capabilities("https://mcp.example/mcp")
    )
    assert result.status == "metadata_missing"
    assert result.supports_automatic_registration is None
    assert set(requested_hosts) == {"mcp.example"}


@pytest.mark.parametrize("failure", ["server_error", "timeout"])
def test_provider_outage_is_unknown_not_unsupported(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("secret upstream URL", request=request)
        return httpx.Response(503)

    monkeypatch.setattr(
        oauth_discovery,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(
        oauth_discovery.discover_oauth_capabilities("https://mcp.example/mcp")
    )
    assert result.status == "unreachable"
    assert result.supports_automatic_registration is None


@pytest.mark.parametrize("hop", ["challenge", "redirect"])
def test_discovery_blocks_metadata_network_hops_without_exposing_internal_url(
    monkeypatch: pytest.MonkeyPatch, hop: str
) -> None:
    from onyx.server.features.mcp import ssrf
    from onyx.server.security.store import _build_env_defaults

    monkeypatch.setattr(ssrf, "get_security_settings", _build_env_defaults)
    requests: list[str] = []
    blocked_url = "http://169.254.169.254/latest/meta-data/"

    async def respond(
        _transport: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        requests.append(str(request.url))
        if hop == "redirect":
            return httpx.Response(302, headers={"location": blocked_url})
        return httpx.Response(
            401,
            headers={"www-authenticate": f'Bearer resource_metadata="{blocked_url}"'},
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", respond)
    result = asyncio.run(
        oauth_discovery.discover_oauth_capabilities("https://8.8.8.8/mcp")
    )
    assert result.status == "unreachable"
    assert result.supports_automatic_registration is None
    assert requests == ["https://8.8.8.8/mcp"]
    assert blocked_url not in result.model_dump_json()


@pytest.mark.parametrize(
    "error,reason",
    [
        (httpx.ConnectError("secret"), "connection_failed"),
        (TimeoutError("secret"), "connection_failed"),
        (RuntimeError("secret"), "oauth_failed"),
        (ExceptionGroup("secret", [RuntimeError("secret")]), "oauth_failed"),
        (
            ExceptionGroup(
                "secret", [RuntimeError("secret"), OAuthRegistrationError("secret")]
            ),
            "client_registration_failed",
        ),
    ],
)
def test_oauth_error_classification_never_exposes_upstream_details(
    error: Exception, reason: str
) -> None:
    result = oauth_discovery.oauth_setup_error(error)
    assert result.extra == {"oauth_error": reason}
    assert "secret" not in result.detail


@pytest.mark.parametrize("outcome", ["allowed", "forbidden", "missing"])
def test_discovery_route_authorizes_in_worker_and_closes_session_before_http(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    import threading
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import Iterator, cast
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from onyx.db.models import MCPServer, User
    from onyx.error_handling.exceptions import register_onyx_exception_handlers
    from onyx.server.features.mcp import api
    from onyx.server.features.mcp.models import MCPOAuthDiscoveryResponse

    app = FastAPI()
    app.include_router(api.admin_router)
    register_onyx_exception_handlers(app)
    route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/admin/mcp/oauth/discover"
    )
    user_dependency = route.dependant.dependencies[0].call
    assert user_dependency is not None
    user = cast(User, SimpleNamespace(email="admin@example.com"))
    app.dependency_overrides[user_dependency] = lambda: user
    events: list[str] = []
    worker_threads: list[int] = []
    http_threads: list[int] = []

    @contextmanager
    def session() -> Iterator[Session]:
        worker_threads.append(threading.get_ident())
        events.append("session_open")
        try:
            yield MagicMock(spec=Session)
        finally:
            events.append("session_closed")

    def lookup(_id: int, _db: Session) -> MCPServer:
        worker_threads.append(threading.get_ident())
        if outcome == "missing":
            raise ValueError("not found")
        return cast(
            MCPServer,
            SimpleNamespace(
                server_url="https://example.com/mcp", name="MCP", owner=user.email
            ),
        )

    def can_manage(_user: User, _server: MCPServer) -> bool:
        worker_threads.append(threading.get_ident())
        return outcome != "forbidden"

    async def discover(url: str) -> MCPOAuthDiscoveryResponse:
        assert url == "https://example.com/mcp"
        assert events == ["session_open", "session_closed"]
        http_threads.append(threading.get_ident())
        return MCPOAuthDiscoveryResponse(status="metadata_missing")

    monkeypatch.setattr(api, "get_session_with_current_tenant", session)
    monkeypatch.setattr(api, "get_mcp_server_by_id", lookup)
    monkeypatch.setattr(api, "can_manage_mcp_server", can_manage)
    monkeypatch.setattr(api, "discover_oauth_capabilities", discover)
    with TestClient(app) as client:
        response = client.post("/admin/mcp/oauth/discover", json={"server_id": 42})
    assert (
        response.status_code
        == {"allowed": 200, "forbidden": 403, "missing": 404}[outcome]
    )
    assert events == ["session_open", "session_closed"]
    assert len(set(worker_threads)) == 1
    if outcome == "allowed":
        assert http_threads[0] != worker_threads[0]
        assert response.json()["supports_automatic_registration"] is None
    else:
        assert http_threads == []
