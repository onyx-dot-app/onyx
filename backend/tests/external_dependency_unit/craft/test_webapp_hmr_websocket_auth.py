"""Auth tests for the session-cookie websocket dependency.

The tenant middleware only runs for HTTP requests, so the websocket
dependency must resolve the tenant from the session token itself. Before
this was fixed, every craft HMR upgrade on a multi-tenant deployment failed
with "RuntimeError: Tenant ID is not set" during dependency resolution.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import WebSocketException
from fastapi.routing import APIWebSocketRoute
from sqlalchemy.orm import Session
from starlette.types import Message, Scope
from starlette.websockets import WebSocket

import onyx.auth.users as users_module
import shared_configs.contextvars as shared_contextvars
from onyx.auth.session_tokens import build_session_token_value
from onyx.auth.users import current_user_from_websocket_cookie, get_redis_strategy
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX, WEB_DOMAIN
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.async_sql_engine import abandon_async_engines
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.features.build.webapp_proxy import public_build_router
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    CURRENT_USER_ID_CONTEXTVAR,
)
from tests.external_dependency_unit.async_client_utils import (
    dispose_loop_async_clients,
)
from tests.external_dependency_unit.conftest import delete_test_user
from tests.external_dependency_unit.craft.db_helpers import make_user


async def _unused_receive() -> Message:
    raise NotImplementedError


async def _unused_send(message: Message) -> None:
    raise NotImplementedError


def _fake_websocket(origin: str | None, cookie: str | None) -> WebSocket:
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if cookie is not None:
        headers.append((b"cookie", cookie.encode()))
    scope = cast(
        Scope,
        {
            "type": "websocket",
            "path": "/build/sessions/x/webapp/_next/webpack-hmr",
            "query_string": b"",
            "headers": headers,
        },
    )
    return WebSocket(scope, receive=_unused_receive, send=_unused_send)


async def _seed_session_token(user_id: UUID, expires_at: datetime) -> str:
    token = secrets.token_urlsafe()
    redis = await get_async_redis_connection()
    await redis.set(
        REDIS_AUTH_KEY_PREFIX + token,
        build_session_token_value(
            user_id=str(user_id),
            tenant_id=POSTGRES_DEFAULT_SCHEMA,
            issued_at=expires_at - timedelta(hours=1),
            expires_at=expires_at,
        ),
        ex=600,
    )
    return token


def _simulate_multi_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenant handling behave like cloud: the websocket task starts with
    no tenant set, and reading it unset raises."""
    monkeypatch.setattr(users_module, "MULTI_TENANT", True)
    monkeypatch.setattr(shared_contextvars, "MULTI_TENANT", True)


def _run_with_unset_tenant(run: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run in a fresh loop with no tenant contextvar set — the state a
    websocket task starts in."""
    reset_token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        asyncio.run(run())
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(reset_token)


def test_hmr_route_uses_shared_cookie_websocket_auth() -> None:
    route = next(
        r
        for r in public_build_router.routes
        if isinstance(r, APIWebSocketRoute) and "webpack-hmr" in r.path
    )
    dependency_calls = [d.call for d in route.dependant.dependencies]
    assert current_user_from_websocket_cookie in dependency_calls


def test_cookie_websocket_auth_sets_tenant_from_session_token(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, standard_account=True)
    db_session.commit()
    _simulate_multi_tenant(monkeypatch)
    abandon_async_engines()

    async def _run() -> None:
        token = await _seed_session_token(
            user.id, datetime.now(timezone.utc) + timedelta(hours=1)
        )
        websocket = _fake_websocket(
            origin=WEB_DOMAIN, cookie=f"{FASTAPI_USERS_AUTH_COOKIE_NAME}={token}"
        )
        dependency = current_user_from_websocket_cookie(
            websocket=websocket, strategy=get_redis_strategy()
        )
        try:
            resolved = await anext(dependency)
            assert resolved.id == user.id
            # The route handler runs while the dependency is suspended at yield
            # and opens DB sessions, so the tenant must still be set here.
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() == POSTGRES_DEFAULT_SCHEMA
            assert CURRENT_USER_ID_CONTEXTVAR.get() == str(user.id)
            await dependency.aclose()
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() is None
            assert CURRENT_USER_ID_CONTEXTVAR.get() is None
        finally:
            await dispose_loop_async_clients()

    try:
        _run_with_unset_tenant(_run)
    finally:
        # Commit the cleanup: the craft conftest teardown rolls the session
        # back, which would undo an uncommitted delete.
        delete_test_user(db_session, user)
        db_session.commit()


def test_cookie_websocket_auth_rejects_expired_session(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, standard_account=True)
    db_session.commit()
    _simulate_multi_tenant(monkeypatch)
    abandon_async_engines()

    async def _run() -> None:
        token = await _seed_session_token(
            user.id, datetime.now(timezone.utc) - timedelta(days=30)
        )
        websocket = _fake_websocket(
            origin=WEB_DOMAIN, cookie=f"{FASTAPI_USERS_AUTH_COOKIE_NAME}={token}"
        )
        dependency = current_user_from_websocket_cookie(
            websocket=websocket, strategy=get_redis_strategy()
        )
        try:
            with pytest.raises(WebSocketException) as exc_info:
                await anext(dependency)
            assert exc_info.value.code == 1008
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() is None
        finally:
            await dispose_loop_async_clients()

    try:
        _run_with_unset_tenant(_run)
    finally:
        # Commit the cleanup: the craft conftest teardown rolls the session
        # back, which would undo an uncommitted delete.
        delete_test_user(db_session, user)
        db_session.commit()


def test_cookie_websocket_auth_rejects_missing_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _simulate_multi_tenant(monkeypatch)

    async def _run() -> None:
        dependency = current_user_from_websocket_cookie(
            websocket=_fake_websocket(origin=WEB_DOMAIN, cookie=None),
            strategy=get_redis_strategy(),
        )
        with pytest.raises(WebSocketException) as exc_info:
            await anext(dependency)
        assert exc_info.value.code == 1008

    _run_with_unset_tenant(_run)
