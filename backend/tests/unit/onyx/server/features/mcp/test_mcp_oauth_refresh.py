"""Regression coverage for MCP OAuth refresh inside
OnyxOAuthClientProvider.async_auth_flow, single-flighted on the cache lock.

Exercises the real OAuthClientProvider/OAuthContext/OnyxTokenStorage code —
client-auth-method branching, endpoint resolution, persistence — mocking only
the DB layer and the outbound network call.
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

import onyx.server.features.mcp.oauth as mcp_oauth
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.db.enums import MCPOAuthProviderMode, MCPTransport
from onyx.db.models import MCPServer as DbMCPServer
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.oauth import make_oauth_provider

_TOKEN_ENDPOINT = "https://gitlab.example.com/oauth/token"
_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"


def _server_stub(transport: MCPTransport = MCPTransport.SSE) -> DbMCPServer:
    # AUTO_DISCOVERY: token endpoint comes from persisted METADATA, matching
    # real DCR-registered servers (KNOWN_PROVIDER never negotiates
    # client_secret_basic — see _build_oauth_admin_config_data).
    return cast(
        DbMCPServer,
        SimpleNamespace(
            id=1,
            name="gitlab",
            server_url="https://mcp.gitlab.example.com",
            transport=transport,
            oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
            oauth_cimd_enabled=True,
            oauth_authorization_endpoint=None,
            oauth_token_endpoint=None,
        ),
    )


class _FakeDbSession:
    def __enter__(self) -> "_FakeDbSession":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class _FakeAsyncHttpClient:
    """Captures the refresh httpx.Request and returns a canned response."""

    def __init__(self, response: httpx.Response, captured: dict[str, Any]):
        self._response = response
        self._captured = captured

    async def __aenter__(self) -> "_FakeAsyncHttpClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def send(self, request: httpx.Request) -> httpx.Response:
        self._captured["sent_request"] = request
        return self._response


@asynccontextmanager
async def _noop_async_shared_lock(*_args: Any, **_kwargs: Any) -> AsyncIterator[None]:
    yield


def _install_mocks(
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict[str, Any],
    *,
    response: httpx.Response | None,
) -> dict[str, Any]:
    """Patch the DB layer OnyxTokenStorage uses and the outbound network call;
    the real OAuthClientProvider/OAuthContext/OnyxTokenStorage code runs
    untouched. Returns a dict capturing the outbound request + persisted config.
    """
    captured: dict[str, Any] = {}

    # Keep this a true unit test: no live cache backend for the single-flight lock.
    monkeypatch.setattr(mcp_oauth, "async_cache_shared_lock", _noop_async_shared_lock)
    monkeypatch.setattr(
        mcp_oauth, "get_session_with_current_tenant", lambda: _FakeDbSession()
    )
    monkeypatch.setattr(
        mcp_oauth,
        "get_connection_config_by_id",
        lambda config_id, _db_session, **_kwargs: SimpleNamespace(id=config_id),
    )
    # extract_connection_data returns the same dict the SDK storage mutates.
    monkeypatch.setattr(
        mcp_oauth,
        "extract_connection_data",
        lambda _config, _apply_mask=False: config_data,
    )

    def _fake_update(config_id: int, _db_session: Any, data: Any = None) -> Any:
        captured["updated_config_data"] = data
        return SimpleNamespace(id=config_id)

    monkeypatch.setattr(mcp_oauth, "update_connection_config", _fake_update)

    fake_client = _FakeAsyncHttpClient(response or httpx.Response(400), captured)
    monkeypatch.setattr(
        mcp_oauth,
        "mcp_ssrf_httpx_client_factory",
        lambda **_kwargs: fake_client,
    )
    return captured


def _token_response(**overrides: Any) -> httpx.Response:
    payload: dict[str, Any] = {
        "access_token": "NEW",
        "token_type": "Bearer",
        "expires_in": 7200,
        "refresh_token": "REFRESH_2",
    }
    payload.update(overrides)
    return httpx.Response(200, json=payload)


def _form_token_response(
    *,
    content_type: str | None = "application/x-www-form-urlencoded; charset=utf-8",
    **overrides: Any,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "access_token": "NEW",
        "token_type": "bearer",
        "expires_in": 7200,
        "refresh_token": "REFRESH_2",
    }
    payload.update(overrides)
    headers = {} if content_type is None else {"content-type": content_type}
    return httpx.Response(200, content=urlencode(payload).encode(), headers=headers)


@pytest.mark.parametrize(
    "content_type",
    ["application/x-www-form-urlencoded; charset=utf-8", None, "application/json"],
)
@pytest.mark.parametrize(
    ("expiry_offset_s", "expected_header"),
    [
        (3600, "Bearer PERSISTED"),
        (-60, None),
    ],
)
def _expired_grant_config() -> dict[str, Any]:
    return {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
        MCPOAuthKeys.METADATA.value: {
            "issuer": "https://gitlab.example.com",
            "authorization_endpoint": "https://gitlab.example.com/oauth/authorize",
            "token_endpoint": _TOKEN_ENDPOINT,
        },
    }


def test_sdk_auth_flow_single_flights_refresh_across_concurrent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STREAMABLE_HTTP path: each tool call builds its own provider, so the
    SDK's per-context lock can't serialize their refreshes. Two concurrent
    async_auth_flows must share one refresh under cache_shared_lock — the
    loser re-reads the winner's grant instead of re-redeeming a single-use
    (rotating) refresh token, which providers like Snowflake reject with
    invalid_grant. Each flow runs on its own thread/event loop, matching
    production (run_async_sync_no_cancel per tool call)."""
    config_data = _expired_grant_config()
    thread_lock = threading.Lock()

    @asynccontextmanager
    async def _serializing_lock(*_args: Any, **_kwargs: Any) -> AsyncIterator[None]:
        acquired = thread_lock.acquire(timeout=10)
        if not acquired:
            raise CacheLockAcquisitionError("held by a concurrent refresher")
        try:
            yield
        finally:
            thread_lock.release()

    _install_mocks(monkeypatch, config_data, response=None)
    monkeypatch.setattr(mcp_oauth, "async_cache_shared_lock", _serializing_lock)

    refresh_posts: list[httpx.Request] = []
    authorized_requests: list[str | None] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode()) if request.content else {}
        if body.get("grant_type") == ["refresh_token"]:
            refresh_posts.append(request)
            if body["refresh_token"] != ["REFRESH_1"] or len(refresh_posts) > 1:
                return httpx.Response(
                    400, json={"error": "invalid_grant"}, request=request
                )
            time.sleep(0.05)  # hold the window so the loser arrives mid-refresh
            return httpx.Response(
                200,
                json={
                    "access_token": "NEW",
                    "token_type": "Bearer",
                    "expires_in": 7200,
                    "refresh_token": "REFRESH_2",
                },
                request=request,
            )
        authorized_requests.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"ok": True}, request=request)

    errors: list[BaseException | None] = [None, None]

    def run_flow(index: int) -> None:
        provider = make_oauth_provider(
            _server_stub(MCPTransport.STREAMABLE_HTTP), 42, None
        )

        async def run() -> None:
            async with httpx.AsyncClient(
                auth=provider,
                transport=httpx.MockTransport(handle_request),
            ) as client:
                await client.post("https://mcp.gitlab.example.com/mcp")

        try:
            asyncio.run(run())
        except BaseException as error:  # noqa: BLE001
            errors[index] = error

    threads = [threading.Thread(target=run_flow, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [None, None]
    assert len(refresh_posts) == 1
    assert authorized_requests and all(
        header == "Bearer NEW" for header in authorized_requests
    )
    assert config_data[MCPOAuthKeys.TOKENS.value]["refresh_token"] == "REFRESH_2"
    assert config_data["headers"]["Authorization"] == "Bearer NEW"


def test_sdk_auth_flow_rechecks_grant_inside_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a prior refresh lands, a later call's flow must not refresh again:
    inside the lock it re-reads the stored grant, sees a valid token, and only
    sends the original request."""
    config_data = _expired_grant_config()
    _install_mocks(monkeypatch, config_data, response=None)

    refresh_posts: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode()) if request.content else {}
        if body.get("grant_type") == ["refresh_token"]:
            refresh_posts.append(request)
            return _token_response()
        return httpx.Response(200, json={"ok": True}, request=request)

    provider = make_oauth_provider(_server_stub(MCPTransport.STREAMABLE_HTTP), 42, None)

    async def run() -> None:
        async with httpx.AsyncClient(
            auth=provider,
            transport=httpx.MockTransport(handle_request),
        ) as client:
            await client.post("https://mcp.gitlab.example.com/mcp")

    asyncio.run(run())
    assert len(refresh_posts) == 1
    assert config_data["headers"]["Authorization"] == "Bearer NEW"

    asyncio.run(run())
    assert len(refresh_posts) == 1


def test_sdk_auth_flow_contention_on_one_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """oauth_flow probes run on the shared app event loop, so a waiter must not
    block that loop while the holder's refresh is in flight — a synchronous
    blocking acquire would stall the holder too and deadlock until timeout.
    Two concurrent flows on ONE loop must still single-flight the refresh."""
    config_data = _expired_grant_config()
    lock_held = False
    lock_released = asyncio.Event()
    lock_released.set()

    @asynccontextmanager
    async def _serializing_lock(*_args: Any, **_kwargs: Any) -> AsyncIterator[None]:
        nonlocal lock_held
        await lock_released.wait()
        lock_held = True
        lock_released.clear()
        try:
            yield
        finally:
            lock_held = False
            lock_released.set()

    _install_mocks(monkeypatch, config_data, response=None)
    monkeypatch.setattr(mcp_oauth, "async_cache_shared_lock", _serializing_lock)

    refresh_posts: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode()) if request.content else {}
        if body.get("grant_type") == ["refresh_token"]:
            refresh_posts.append(request)
            if body["refresh_token"] != ["REFRESH_1"] or len(refresh_posts) > 1:
                return httpx.Response(
                    400, json={"error": "invalid_grant"}, request=request
                )
            return _token_response()
        return httpx.Response(200, json={"ok": True}, request=request)

    async def run() -> list[httpx.Response]:
        async def flow() -> httpx.Response:
            provider = make_oauth_provider(
                _server_stub(MCPTransport.STREAMABLE_HTTP), 42, None
            )
            async with httpx.AsyncClient(
                auth=provider,
                transport=httpx.MockTransport(handle_request),
            ) as client:
                return await client.post("https://mcp.gitlab.example.com/mcp")

        return list(await asyncio.gather(flow(), flow()))

    responses = asyncio.run(run())

    assert all(response.status_code == 200 for response in responses)
    assert len(refresh_posts) == 1
    assert config_data[MCPOAuthKeys.TOKENS.value]["refresh_token"] == "REFRESH_2"
    assert config_data["headers"]["Authorization"] == "Bearer NEW"
