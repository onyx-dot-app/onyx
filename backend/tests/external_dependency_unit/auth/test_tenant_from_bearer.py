"""External-dependency-unit tests for resolving the tenant from an opaque Redis
session token sent in the Authorization header (the native-mobile bearer path).
Exercises the real Redis store; mocks nothing."""

import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi import Request

from ee.onyx.server.middleware.tenant_tracking import _tenant_from_bearer_session_token
from onyx.auth.constants import API_KEY_HEADER_ALTERNATIVE_NAME
from onyx.auth.constants import API_KEY_HEADER_NAME
from onyx.configs.app_configs import REDIS_AUTH_KEY_PREFIX
from onyx.redis.redis_pool import get_async_redis_connection


@pytest_asyncio.fixture(autouse=True)
async def _fresh_async_redis() -> AsyncIterator[None]:
    """`get_async_redis_connection` caches a process-wide connection bound to the
    event loop that first created it. With function-scoped test loops, reusing it
    across tests raises "Event loop is closed". Reset the singleton around each test
    (and close the connection on the test's own loop) so every test gets a fresh
    connection and nothing leaks to GC on a closed loop."""
    import onyx.redis.redis_pool as redis_pool

    redis_pool._async_redis_connection = None
    yield
    conn = redis_pool._async_redis_connection
    redis_pool._async_redis_connection = None
    if conn is not None:
        await conn.aclose()


def _request_with_bearer(token: str, header_name: str = API_KEY_HEADER_NAME) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(header_name.lower().encode(), f"Bearer {token}".encode())],
        }
    )


@pytest.mark.asyncio
async def test_resolves_tenant_from_redis_bearer_token() -> None:
    token = f"test-{uuid.uuid4().hex}"
    tenant = "tenant_abc123"
    redis = await get_async_redis_connection()
    await redis.set(
        f"{REDIS_AUTH_KEY_PREFIX}{token}",
        json.dumps({"sub": str(uuid.uuid4()), "tenant_id": tenant}),
        ex=60,
    )
    try:
        resolved = await _tenant_from_bearer_session_token(_request_with_bearer(token))
        assert resolved == tenant
    finally:
        await redis.delete(f"{REDIS_AUTH_KEY_PREFIX}{token}")


@pytest.mark.asyncio
async def test_resolves_tenant_from_alternative_auth_header() -> None:
    token = f"test-{uuid.uuid4().hex}"
    tenant = "tenant_alt123"
    redis = await get_async_redis_connection()
    await redis.set(
        f"{REDIS_AUTH_KEY_PREFIX}{token}",
        json.dumps({"sub": str(uuid.uuid4()), "tenant_id": tenant}),
        ex=60,
    )
    try:
        resolved = await _tenant_from_bearer_session_token(
            _request_with_bearer(token, API_KEY_HEADER_ALTERNATIVE_NAME)
        )
        assert resolved == tenant
    finally:
        await redis.delete(f"{REDIS_AUTH_KEY_PREFIX}{token}")


@pytest.mark.asyncio
async def test_unknown_token_returns_none() -> None:
    resolved = await _tenant_from_bearer_session_token(
        _request_with_bearer("does-not-exist")
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_api_key_token_does_not_resolve_a_session() -> None:
    # An API-key-style token is not a stored session token, so the Redis lookup
    # misses and no tenant is resolved via the bearer path. (Valid API keys are
    # resolved earlier by extract_tenant_from_auth_header and never reach here.)
    resolved = await _tenant_from_bearer_session_token(
        _request_with_bearer("on_tenant_x.somerandom")
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_no_authorization_header_returns_none() -> None:
    req = Request({"type": "http", "headers": []})
    assert await _tenant_from_bearer_session_token(req) is None


@pytest.mark.asyncio
async def test_malformed_tenant_id_is_rejected() -> None:
    # A token whose stored tenant_id is not a valid schema name must be rejected,
    # not used to build a SQL schema reference.
    token = f"test-{uuid.uuid4().hex}"
    redis = await get_async_redis_connection()
    await redis.set(
        f"{REDIS_AUTH_KEY_PREFIX}{token}",
        json.dumps({"sub": str(uuid.uuid4()), "tenant_id": "bad; DROP TABLE users"}),
        ex=60,
    )
    try:
        with pytest.raises(HTTPException):
            await _tenant_from_bearer_session_token(_request_with_bearer(token))
    finally:
        await redis.delete(f"{REDIS_AUTH_KEY_PREFIX}{token}")
