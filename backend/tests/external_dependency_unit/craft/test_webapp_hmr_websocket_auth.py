"""Auth tests for the webapp HMR websocket dependency.

The tenant middleware only runs for HTTP requests, so the websocket
dependency must resolve the tenant from the session token itself. Before
this was fixed, every HMR upgrade on a multi-tenant deployment failed with
"RuntimeError: Tenant ID is not set" during dependency resolution.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import pytest
from fastapi import WebSocketException
from sqlalchemy.orm import Session
from starlette.types import Message, Scope
from starlette.websockets import WebSocket

import onyx.server.features.build.webapp_proxy as webapp_proxy
import shared_configs.contextvars as shared_contextvars
from onyx.auth.session_tokens import build_session_token_value
from onyx.auth.users import get_redis_strategy
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX, WEB_DOMAIN
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.async_sql_engine import (
    abandon_async_engines,
    reset_sqlalchemy_async_engine,
)
from onyx.redis.redis_pool import get_async_redis_connection
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
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


async def _dispose_async_clients() -> None:
    """Close loop-bound clients before asyncio.run tears the loop down."""
    await reset_sqlalchemy_async_engine()
    redis = await get_async_redis_connection()
    await redis.aclose()


def _simulate_multi_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenant handling behave like cloud: the websocket task starts with
    no tenant set, and reading it unset raises."""
    monkeypatch.setattr(webapp_proxy, "MULTI_TENANT", True)
    monkeypatch.setattr(shared_contextvars, "MULTI_TENANT", True)


def test_hmr_websocket_auth_sets_tenant_from_session_token(
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
        dependency = webapp_proxy._current_webapp_websocket_user(
            websocket=websocket, strategy=get_redis_strategy()
        )
        try:
            resolved = await anext(dependency)
            assert resolved.id == user.id
            # The route handler runs while the dependency is suspended at yield
            # and opens DB sessions, so the tenant must still be set here.
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() == POSTGRES_DEFAULT_SCHEMA
            await dependency.aclose()
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() is None
        finally:
            await _dispose_async_clients()

    reset_token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        asyncio.run(_run())
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(reset_token)
        delete_test_user(db_session, user)


def test_hmr_websocket_auth_rejects_expired_session(
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
        dependency = webapp_proxy._current_webapp_websocket_user(
            websocket=websocket, strategy=get_redis_strategy()
        )
        try:
            with pytest.raises(WebSocketException):
                await anext(dependency)
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() is None
        finally:
            await _dispose_async_clients()

    reset_token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        asyncio.run(_run())
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(reset_token)
        delete_test_user(db_session, user)


def test_hmr_websocket_auth_rejects_missing_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _simulate_multi_tenant(monkeypatch)

    async def _run() -> None:
        dependency = webapp_proxy._current_webapp_websocket_user(
            websocket=_fake_websocket(origin=WEB_DOMAIN, cookie=None),
            strategy=get_redis_strategy(),
        )
        with pytest.raises(WebSocketException):
            await anext(dependency)

    reset_token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        asyncio.run(_run())
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(reset_token)
