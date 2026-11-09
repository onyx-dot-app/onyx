"""Streaming contracts for enterprise middleware."""

import asyncio
import json
import logging
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ee.onyx.server.middleware import license_enforcement, tenant_tracking, tier_gate
from ee.onyx.server.middleware.license_enforcement import (
    license_enforcement_middleware,
)
from ee.onyx.server.middleware.tier_gate import tier_gate_middleware
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import ApplicationStatus, Tier
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

LOGGER = logging.LoggerAdapter(logging.getLogger(__name__))


async def _receive() -> Message:
    return {"type": "http.disconnect"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [
        license_enforcement_middleware,
        tier_gate_middleware,
        tenant_tracking.tenant_id_middleware,
    ],
)
@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_non_http_passthrough(
    factory: Callable[[ASGIApp, logging.LoggerAdapter], ASGIApp], scope_type: str
) -> None:
    app = AsyncMock()
    send = AsyncMock()
    scope: Scope = {"type": scope_type}
    await factory(app, LOGGER)(scope, _receive, send)
    app.assert_awaited_once_with(scope, _receive, send)


@pytest.mark.asyncio
async def test_tenant_context_lasts_through_stream_and_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tenant_tracking, "MULTI_TENANT", True)
    monkeypatch.setattr(tenant_tracking, "is_tenant_gated", lambda _tenant: False)

    async def resolve(request: Request, _logger: logging.LoggerAdapter) -> str:
        return request.headers["x-test-tenant"]

    monkeypatch.setattr(tenant_tracking, "_get_tenant_id_from_request", resolve)
    ready = asyncio.Event()
    active = 0

    async def app(scope: Scope, _receive: Receive, send: Send) -> None:
        nonlocal active
        expected = dict(scope["headers"])[b"x-test-tenant"].decode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        active += 1
        if active == 2:
            ready.set()
        await ready.wait()
        for body in (b"first\n", b"second\n"):
            await asyncio.sleep(0)
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() == expected
            await send({"type": "http.response.body", "body": body, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == expected

    middleware = tenant_tracking.tenant_id_middleware(app, LOGGER)

    async def run(tenant: str) -> None:
        original = CURRENT_TENANT_ID_CONTEXTVAR.get()
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/chat",
            "headers": [(b"x-test-tenant", tenant.encode())],
        }
        send = AsyncMock()
        await middleware(scope, _receive, send)
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == original
        assert [call.args[0]["body"] for call in send.await_args_list[1:]] == [
            b"first\n",
            b"second\n",
            b"",
        ]

    await asyncio.gather(run("tenant_a"), run("tenant_b"))


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_tenant_error_does_not_replace_started_response(
    monkeypatch: pytest.MonkeyPatch, started: bool
) -> None:
    monkeypatch.setattr(tenant_tracking, "MULTI_TENANT", False)
    original = CURRENT_TENANT_ID_CONTEXTVAR.get()
    error = OnyxError(OnyxErrorCode.UNAUTHORIZED, "denied")

    async def app(_scope: Scope, _receive: Receive, send: Send) -> None:
        if started:
            await send({"type": "http.response.start", "status": 200, "headers": []})
        raise error

    send = AsyncMock()
    middleware = tenant_tracking.tenant_id_middleware(app, LOGGER)
    scope: Scope = {"type": "http", "method": "GET", "path": "/chat", "headers": []}
    if started:
        with pytest.raises(OnyxError, match="denied"):
            await middleware(scope, _receive, send)
        assert send.await_count == 1
    else:
        await middleware(scope, _receive, send)
        assert (
            send.await_args_list[0].args[0]["status"]
            == OnyxErrorCode.UNAUTHORIZED.status_code
        )
    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory", [license_enforcement_middleware, tier_gate_middleware]
)
@pytest.mark.parametrize("denied", [False, True])
async def test_gating_sends_denial_or_preserves_send(
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[[ASGIApp, logging.LoggerAdapter], ASGIApp],
    denied: bool,
) -> None:
    monkeypatch.setattr(
        tier_gate, "get_tier", lambda _: Tier.COMMUNITY if denied else Tier.ENTERPRISE
    )
    metadata = MagicMock(
        status=ApplicationStatus.GATED_ACCESS if denied else ApplicationStatus.ACTIVE,
        used_seats=1,
        seats=5,
    )
    monkeypatch.setattr(
        license_enforcement, "get_cached_license_metadata", lambda _: metadata
    )
    monkeypatch.setattr(license_enforcement, "_should_recheck_gated", lambda: False)
    monkeypatch.setattr(
        license_enforcement, "maybe_schedule_license_reclaim", lambda *_: None
    )
    app = AsyncMock()
    send = AsyncMock()
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/admin/hooks",
        "headers": [],
    }
    await factory(app, LOGGER)(scope, _receive, send)
    if denied:
        app.assert_not_awaited()
        assert send.await_args_list[0].args[0]["status"] == 402
        payload = json.loads(send.await_args_list[1].args[0]["body"])
        if factory is tier_gate_middleware:
            assert payload["error_code"] == "FEATURE_NOT_AVAILABLE"
        else:
            assert payload["detail"]["error"] == "license_expired"
    else:
        app.assert_awaited_once_with(scope, _receive, send)


@pytest.mark.asyncio
async def test_tenant_context_resets_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tenant_tracking, "MULTI_TENANT", False)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("outer_context")

    async def app(_scope: Scope, _receive: Receive, send: Send) -> None:
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() != "outer_context"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise asyncio.CancelledError

    try:
        scope: Scope = {"type": "http", "method": "GET", "path": "/chat", "headers": []}
        with pytest.raises(asyncio.CancelledError):
            await tenant_tracking.tenant_id_middleware(app, LOGGER)(
                scope, _receive, AsyncMock()
            )
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() == "outer_context"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
