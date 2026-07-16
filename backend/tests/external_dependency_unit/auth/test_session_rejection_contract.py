"""
The strategy's classification must survive the fastapi-users plumbing (which
collapses invalid tokens to None) and land as an error_code in the /me 403 body.
The classification matrix lives in test_session_token_strategy.py.
"""

import json
import secrets
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from httpx import AsyncClient
from sqlalchemy.orm import Session

from onyx.auth.users import TenantAwareRedisStrategy
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.manage.users import router as user_router
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(user_router)
    register_onyx_exception_handlers(fastapi_app)
    return fastapi_app


def _client(app: FastAPI, token: str) -> AsyncClient:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    client.cookies.set(FASTAPI_USERS_AUTH_COOKIE_NAME, token)
    return client


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
    finally:
        redis.delete(redis_key)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context", "db_session")
async def test_absent_session_yields_403_with_unrecognized_code(
    app: FastAPI,
) -> None:
    async with _client(app, secrets.token_urlsafe()) as client:
        response = await client.get("/me")

    assert response.status_code == 403
    assert response.json()["error_code"] == "SESSION_UNRECOGNIZED"
