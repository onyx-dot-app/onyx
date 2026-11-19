"""
The strategy's classification must survive the fastapi-users plumbing (which
collapses invalid tokens to None) and land as an error_code in the /me 403 body.
An unrecognized token's response also expires the cookie.
The classification matrix lives in test_session_token_strategy.py.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import Session

import onyx.auth.users as auth_users
import onyx.server.manage.users as manage_users
from onyx.auth.users import TenantAwareRedisStrategy, current_chat_accessible_user
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.models import User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.manage.users import router as user_router
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(user_router)
    register_onyx_exception_handlers(fastapi_app)

    @fastapi_app.get("/chat-accessible")
    def chat_accessible(
        user: User = Depends(current_chat_accessible_user),
    ) -> dict[str, str]:
        return {"user_id": str(user.id)}

    return fastapi_app


def _client(app: FastAPI, token: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    client.cookies.set(FASTAPI_USERS_AUTH_COOKIE_NAME, token)
    return client


def _assert_clears_session_cookie(response: httpx.Response) -> None:
    session_cookies = [
        cookie
        for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith(f"{FASTAPI_USERS_AUTH_COOKIE_NAME}=")
    ]
    assert len(session_cookies) == 1
    attributes = [part.strip() for part in session_cookies[0].split(";")]
    assert attributes[0] == f'{FASTAPI_USERS_AUTH_COOKIE_NAME}=""'
    assert "Max-Age=0" in attributes
    assert "Path=/" in attributes
    assert not any(part.lower().startswith("domain=") for part in attributes)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_expired_session_yields_403_with_expired_code(
    app: FastAPI, db_session: Session
) -> None:
    # Precondition.
    user = create_test_user(db_session, "session_contract_expired")
    strategy = TenantAwareRedisStrategy()
    token = await strategy.write_token(user)
    redis = get_raw_redis_client()
    redis_key = REDIS_AUTH_KEY_PREFIX + token
    try:
        # Push the logical expiry into the past; the physical key stays put.
        raw_value = cast(bytes | None, redis.get(redis_key))
        assert raw_value is not None
        data = json.loads(raw_value)
        data["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        redis.set(redis_key, json.dumps(data), keepttl=True)

        # Under test.
        async with _client(app, token) as client:
            response = await client.get("/me")

        # Postcondition.
        assert response.status_code == 403
        assert response.json()["error_code"] == "SESSION_EXPIRED"
        # The cookie stays for the grace window so other tabs can name the reason.
        assert "set-cookie" not in response.headers
    finally:
        redis.delete(redis_key)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context", "db_session")
async def test_absent_session_yields_403_with_unrecognized_code_and_clears_cookie(
    app: FastAPI,
) -> None:
    async with _client(app, secrets.token_urlsafe()) as client:
        response = await client.get("/me")

    assert response.status_code == 403
    assert response.json()["error_code"] == "SESSION_UNRECOGNIZED"
    _assert_clears_session_cookie(response)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context", "db_session")
async def test_unreadable_session_yields_403_with_unrecognized_code_and_clears_cookie(
    app: FastAPI,
) -> None:
    token = secrets.token_urlsafe()
    redis = get_raw_redis_client()
    redis_key = REDIS_AUTH_KEY_PREFIX + token
    redis.set(redis_key, "not json", ex=60)
    try:
        async with _client(app, token) as client:
            response = await client.get("/me")
    finally:
        redis.delete(redis_key)

    assert response.status_code == 403
    assert response.json()["error_code"] == "SESSION_UNRECOGNIZED"
    _assert_clears_session_cookie(response)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context", "db_session")
@pytest.mark.parametrize("path", ["/me", "/chat-accessible"])
async def test_anonymous_fallback_clears_unrecognized_cookie(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setattr(manage_users, "anonymous_user_enabled", lambda **_: True)
    monkeypatch.setattr(auth_users, "anonymous_user_enabled", lambda **_: True)

    async with _client(app, secrets.token_urlsafe()) as client:
        response = await client.get(path)

    assert response.status_code == 200
    _assert_clears_session_cookie(response)
