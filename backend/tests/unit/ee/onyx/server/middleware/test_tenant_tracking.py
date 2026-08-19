"""Tests for the api-server tenant-resolution middleware.

Focus: tenant resolution must **fail closed**. A transient Redis error during
the cookie- or Bearer-header session-token lookup must propagate (500), not get
swallowed into a silent default-schema fallback — otherwise a request could be
served against the wrong tenant. (Contrast license enforcement, which fails
*open*; tenant routing is a data-isolation boundary and must not.)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ee.onyx.server.middleware import tenant_tracking
from onyx.server.middleware import api_prefix
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

MODULE = "ee.onyx.server.middleware.tenant_tracking"


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/me", "headers": raw})


def test_custom_api_prefix_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_prefix, "APP_API_PREFIX", "v2")
    assert tenant_tracking._is_path_allowed("/v2/auth/login") is True
    assert tenant_tracking._is_path_allowed("/v2/chat") is False


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
def test_probe_paths_skip_tenant_resolution_under_api_prefix(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Probes must never reach the Redis session lookup, prefixed or not."""
    monkeypatch.setattr(api_prefix, "APP_API_PREFIX", "v2")
    stripped = api_prefix.strip_api_prefix(f"/v2{path}")
    assert stripped in tenant_tracking.TENANT_RESOLUTION_SKIP_PATHS


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


@pytest.mark.asyncio
@patch(f"{MODULE}.retrieve_auth_token_data_from_bearer")
@patch(f"{MODULE}.retrieve_auth_token_data_from_redis")
async def test_client_supplied_cookie_cannot_select_a_workspace(
    mock_cookie: AsyncMock,
    mock_bearer: AsyncMock,
) -> None:
    """Every accepted source is signed or server-issued. A bare cookie naming a
    schema is attacker input, and honoring it would hand an unauthenticated
    caller that workspace on any route that reads tenant-scoped data."""
    mock_cookie.return_value = None
    mock_bearer.return_value = None

    req = _request({"cookie": "onyx_tid=tenant_victim"})
    tenant_id = await tenant_tracking._get_tenant_id_from_request(req, MagicMock())
    assert tenant_id == POSTGRES_DEFAULT_SCHEMA
