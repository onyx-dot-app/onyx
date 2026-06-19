"""Tests for the api-server tenant-resolution middleware.

Focus: tenant resolution must **fail closed**. A transient Redis error during
the cookie- or Bearer-header session-token lookup must propagate (500), not get
swallowed into a silent default-schema fallback — otherwise a request could be
served against the wrong tenant. (Contrast license enforcement, which fails
*open*; tenant routing is a data-isolation boundary and must not.)
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ee.onyx.server.middleware import tenant_tracking
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

MODULE = "ee.onyx.server.middleware.tenant_tracking"


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/me", "headers": raw})


@pytest.mark.asyncio
@patch(f"{MODULE}.retrieve_auth_token_data_from_bearer")
@patch(f"{MODULE}.retrieve_auth_token_data_from_redis")
async def test_bearer_redis_error_propagates_not_default(
    mock_cookie: AsyncMock,
    mock_bearer: AsyncMock,
) -> None:
    """A Redis failure on the Bearer lookup must surface as 500, not fall back to
    the default schema (the bug the `finally` block used to mask)."""
    mock_cookie.return_value = None
    mock_bearer.side_effect = ValueError("redis down")

    req = _request({"Authorization": "Bearer opaque_session_token"})
    with pytest.raises(HTTPException) as exc:
        await tenant_tracking._get_tenant_id_from_request(req, MagicMock())
    assert exc.value.status_code == 500


@pytest.mark.asyncio
@patch(f"{MODULE}.retrieve_auth_token_data_from_bearer")
@patch(f"{MODULE}.retrieve_auth_token_data_from_redis")
async def test_cookie_redis_error_propagates_not_default(
    mock_cookie: AsyncMock,
    mock_bearer: AsyncMock,
) -> None:
    """Same fail-closed guarantee for the pre-existing cookie path."""
    mock_cookie.side_effect = ValueError("redis down")

    req = _request()
    with pytest.raises(HTTPException) as exc:
        await tenant_tracking._get_tenant_id_from_request(req, MagicMock())
    assert exc.value.status_code == 500
    mock_bearer.assert_not_called()


@pytest.mark.asyncio
@patch(f"{MODULE}.retrieve_auth_token_data_from_bearer")
@patch(f"{MODULE}.retrieve_auth_token_data_from_redis")
async def test_bearer_resolves_tenant(
    mock_cookie: AsyncMock,
    mock_bearer: AsyncMock,
) -> None:
    """Happy path: a mobile Bearer token resolves its tenant from Redis."""
    mock_cookie.return_value = None
    mock_bearer.return_value = {"tenant_id": "tenant_abc123"}

    req = _request({"Authorization": "Bearer opaque_session_token"})
    tenant_id = await tenant_tracking._get_tenant_id_from_request(req, MagicMock())
    assert tenant_id == "tenant_abc123"


@pytest.mark.asyncio
@patch(f"{MODULE}.retrieve_auth_token_data_from_bearer")
@patch(f"{MODULE}.retrieve_auth_token_data_from_redis")
async def test_no_auth_returns_default_schema(
    mock_cookie: AsyncMock,
    mock_bearer: AsyncMock,
) -> None:
    """Unauthenticated requests still fall back to the default schema (the normal
    `finally` path is preserved — the guard only suppresses it on error)."""
    mock_cookie.return_value = None
    mock_bearer.return_value = None

    req = _request()
    tenant_id = await tenant_tracking._get_tenant_id_from_request(req, MagicMock())
    assert tenant_id == POSTGRES_DEFAULT_SCHEMA
