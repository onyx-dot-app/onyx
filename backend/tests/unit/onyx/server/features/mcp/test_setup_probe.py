import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from onyx.db.enums import MCPTransport
from onyx.server.features.mcp import oauth_discovery, setup_probe
from onyx.utils.url import SSRFException


def _rpc_result(payload: dict) -> dict:
    if payload["method"] == "initialize":
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "Support tools", "version": "1"},
        }
    assert payload["method"] == "tools/list"
    return {"tools": [{"name": "lookup_ticket", "inputSchema": {"type": "object"}}]}


def test_public_requires_mcp_initialization_and_lists_tools_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    methods: list[str] = []
    events: list[setup_probe.MCPProbeProgress] = []

    async def progress(event: setup_probe.MCPProbeProgress) -> None:
        if event["stage"] == "authentication" and event["state"] == "pending":
            assert methods[0] == "initialize"
            assert "tools/list" not in methods
        events.append(event)

    def respond(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.method == "GET":
            return httpx.Response(405)
        payload = json.loads(request.content)
        methods.append(payload["method"])
        if "id" not in payload:
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": _rpc_result(payload),
            },
        )

    monkeypatch.setattr(
        setup_probe,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(
        setup_probe.probe_mcp_server("https://mcp.example/mcp", progress)
    )
    assert result.model_dump() == {
        "kind": "public",
        "transport": MCPTransport.STREAMABLE_HTTP,
        "tool_count": 1,
        "server_name": "Support tools",
    }
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    assert [(event["stage"], event["state"]) for event in events] == [
        ("contacting_server", "pending"),
        ("contacting_server", "success"),
        ("authentication", "pending"),
        ("authentication", "success"),
    ]


def test_stream_close_cancels_inflight_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        cancelled = asyncio.Event()

        async def probe(_url: str, progress: setup_probe.Progress) -> None:
            try:
                await progress(
                    {
                        "type": "progress",
                        "stage": "contacting_server",
                        "state": "pending",
                    }
                )
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(setup_probe, "probe_mcp_server", probe)
        stream = setup_probe.stream_mcp_probe("https://mcp.example/mcp")
        assert json.loads(await anext(stream))["state"] == "pending"
        await stream.aclose()
        assert cancelled.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("failure", [None, "probe", "serialization"])
def test_stream_delivers_one_terminal_result_after_producer_failure(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    async def probe(
        _url: str, _progress: setup_probe.Progress
    ) -> setup_probe.MCPSetupProbeResult:
        if failure == "probe":
            raise RuntimeError("Probe failed")
        return setup_probe.MCPPublicProbeResult(
            transport=MCPTransport.STREAMABLE_HTTP,
            tool_count=1,
            server_name="Support tools",
        )

    def fail_serialization(*_: object, **__: object) -> None:
        raise ValueError("Serialization failed")

    monkeypatch.setattr(setup_probe, "probe_mcp_server", probe)
    if failure == "serialization":
        monkeypatch.setattr(
            setup_probe.MCPPublicProbeResult, "model_dump", fail_serialization
        )

    async def collect() -> list[dict]:
        return [
            json.loads(event)
            async for event in setup_probe.stream_mcp_probe("https://mcp.example/mcp")
        ]

    async def run() -> list[dict]:
        return await asyncio.wait_for(collect(), timeout=1)

    events = asyncio.run(run())
    assert len(events) == 1
    assert events[0]["type"] == "result"
    if failure is None:
        assert events[0]["result"] == {
            "kind": "public",
            "transport": "STREAMABLE_HTTP",
            "tool_count": 1,
            "server_name": "Support tools",
        }
    else:
        assert events[0]["result"] == {
            "kind": "unreachable",
            "reason": "connection_failed",
        }


@pytest.mark.parametrize("registration", [True, False])
def test_oauth_uses_post_challenge_and_only_reads_metadata(
    monkeypatch: pytest.MonkeyPatch, registration: bool
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "authorization" not in request.headers
        if request.method == "POST":
            assert request.url.path == "/mcp"
            assert json.loads(request.content)["method"] == "initialize"
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": 'Bearer resource_metadata="https://mcp.example/metadata"'
                },
            )
        assert request.method == "GET"
        if request.url.path == "/metadata":
            return httpx.Response(
                200,
                json={
                    "resource": "https://mcp.example/mcp",
                    "authorization_servers": ["https://identity.example"],
                },
            )
        return httpx.Response(
            200,
            json={
                "issuer": "https://identity.example",
                "authorization_endpoint": "https://identity.example/authorize",
                "token_endpoint": "https://identity.example/token",
                "response_types_supported": ["code"],
                "registration_endpoint": "https://identity.example/register"
                if registration
                else None,
            },
        )

    def factory(**_: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(setup_probe, "mcp_ssrf_httpx_client_factory", factory)
    monkeypatch.setattr(oauth_discovery, "mcp_ssrf_httpx_client_factory", factory)
    result = asyncio.run(setup_probe.probe_mcp_server("https://mcp.example/mcp"))
    assert result.kind == "oauth"
    assert result.discovery.supports_automatic_registration is registration
    assert result.transport is None
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/mcp"),
        ("GET", "/metadata"),
        ("GET", "/.well-known/oauth-authorization-server"),
    ]


def test_missing_oauth_metadata_is_unknown_auth_not_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401 if request.url.path == "/mcp" else 404)

    def factory(**_: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(setup_probe, "mcp_ssrf_httpx_client_factory", factory)
    monkeypatch.setattr(oauth_discovery, "mcp_ssrf_httpx_client_factory", factory)
    result = asyncio.run(setup_probe.probe_mcp_server("https://mcp.example/mcp"))
    assert result.model_dump() == {"kind": "auth_unknown", "transport": None}


@pytest.mark.parametrize("failure", ["html", "network", "blocked"])
def test_failure_is_safe_and_ssrf_block_never_falls_back(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if failure == "blocked":
            raise SSRFException("private URL and secret response")
        if failure == "network":
            raise httpx.ConnectError("private URL and secret response")
        return httpx.Response(200, text="<html>private URL and secret response</html>")

    monkeypatch.setattr(
        setup_probe,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(setup_probe.probe_mcp_server("https://mcp.example/mcp"))
    assert result.model_dump() == {
        "kind": "unreachable",
        "reason": "blocked" if failure == "blocked" else "connection_failed",
    }
    assert "private" not in result.model_dump_json()
    assert methods == (["POST"] if failure == "blocked" else ["POST", "GET"])


def test_compatible_sse_fallback_initializes_and_lists_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: asyncio.Queue[bytes] = asyncio.Queue()
    requests: list[tuple[str, str]] = []

    class EventStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"event: endpoint\ndata: /messages\n\n"
            while True:
                yield await messages.get()

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/sse":
            if request.method == "POST":
                return httpx.Response(405)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=EventStream()
            )
        assert request.url.path == "/messages"
        payload = json.loads(request.content)
        if "id" in payload:
            result = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": _rpc_result(payload),
            }
            await messages.put(
                f"event: message\ndata: {json.dumps(result)}\n\n".encode()
            )
        return httpx.Response(202)

    monkeypatch.setattr(
        setup_probe,
        "mcp_ssrf_httpx_client_factory",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = asyncio.run(setup_probe.probe_mcp_server("https://mcp.example/sse"))
    assert result.kind == "public"
    assert result.transport == MCPTransport.SSE
    assert result.tool_count == 1
    assert requests[:2] == [("POST", "/sse"), ("GET", "/sse")]


def test_protected_sse_message_endpoint_uses_its_oauth_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str]] = []

    class EventStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"event: endpoint\ndata: /messages\n\n"
            await asyncio.Event().wait()

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/sse":
            if request.method == "POST":
                return httpx.Response(405)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=EventStream()
            )
        if request.url.path == "/messages":
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
                    "resource": "https://mcp.example/sse",
                    "authorization_servers": ["https://identity.example"],
                },
            )
        return httpx.Response(
            200,
            json={
                "issuer": "https://identity.example",
                "authorization_endpoint": "https://identity.example/authorize",
                "token_endpoint": "https://identity.example/token",
                "response_types_supported": ["code"],
                "client_id_metadata_document_supported": True,
            },
        )

    def factory(**_: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(setup_probe, "mcp_ssrf_httpx_client_factory", factory)
    monkeypatch.setattr(oauth_discovery, "mcp_ssrf_httpx_client_factory", factory)
    result = asyncio.run(setup_probe.probe_mcp_server("https://mcp.example/sse"))
    assert result.kind == "oauth"
    assert result.transport == MCPTransport.SSE
    assert result.discovery.supports_automatic_registration is True
    assert requests == [
        ("POST", "/sse"),
        ("GET", "/sse"),
        ("POST", "/messages"),
        ("GET", "/metadata"),
        ("GET", "/.well-known/oauth-authorization-server"),
    ]


@pytest.mark.parametrize("authorized", [True, False])
@pytest.mark.parametrize("path", ["/admin/mcp/probe", "/admin/mcp/probe/stream"])
def test_probe_route_checks_permission_before_network(
    monkeypatch: pytest.MonkeyPatch, authorized: bool, path: str
) -> None:
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient

    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import (
        OnyxError,
        register_onyx_exception_handlers,
    )
    from onyx.server.features.mcp import api

    app = FastAPI()
    app.include_router(api.admin_router)
    register_onyx_exception_handlers(app)
    route = next(
        route
        for route in api.admin_router.routes
        if isinstance(route, APIRoute) and route.path == path
    )
    dependency = route.dependant.dependencies[0].call
    assert dependency is not None

    def permission() -> None:
        if not authorized:
            raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)

    app.dependency_overrides[dependency] = permission
    probe = AsyncMock(return_value=setup_probe.MCPUnknownAuthProbeResult())
    monkeypatch.setattr(api, "probe_mcp_server", probe)
    monkeypatch.setattr(setup_probe, "probe_mcp_server", probe)
    with TestClient(app) as test_client:
        response = test_client.post(
            path, json={"server_url": "https://mcp.example/mcp"}
        )
    assert response.status_code == (200 if authorized else 403)
    if authorized:
        assert probe.await_count == 1
        awaited = probe.await_args
        assert awaited is not None
        assert awaited.args[0] == "https://mcp.example/mcp"
        if path.endswith("/stream"):
            assert response.headers["X-Accel-Buffering"] == "no"
            assert response.headers["Cache-Control"] == "no-cache, no-transform"
            events = [json.loads(line) for line in response.text.splitlines()]
            assert events == [
                {
                    "type": "result",
                    "result": {"kind": "auth_unknown", "transport": None},
                }
            ]
        else:
            assert response.json() == {"kind": "auth_unknown", "transport": None}
    else:
        probe.assert_not_called()
