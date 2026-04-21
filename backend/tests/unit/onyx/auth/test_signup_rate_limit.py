"""Unit tests for the per-IP signup rate limiter."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import Request

from onyx.auth import signup_rate_limit as rl
from onyx.auth.signup_rate_limit import _bucket_key
from onyx.auth.signup_rate_limit import _client_ip
from onyx.auth.signup_rate_limit import _PER_IP_PER_HOUR
from onyx.auth.signup_rate_limit import enforce_signup_rate_limit
from onyx.error_handling.exceptions import OnyxError


def _make_request(
    xff: str | None = None, client_host: str | None = "1.2.3.4"
) -> Request:
    scope: dict = {
        "type": "http",
        "method": "POST",
        "path": "/auth/register",
        "headers": [],
    }
    if xff is not None:
        scope["headers"].append((b"x-forwarded-for", xff.encode()))
    if client_host is not None:
        scope["client"] = (client_host, 54321)
    return Request(scope)


# ---------- IP extraction ----------


def test_client_ip_prefers_xff_first_entry() -> None:
    req = _make_request(xff="203.0.113.9, 10.0.0.1, 10.0.0.2")
    assert _client_ip(req) == "203.0.113.9"


def test_client_ip_falls_back_to_request_client_host() -> None:
    req = _make_request(xff=None, client_host="198.51.100.7")
    assert _client_ip(req) == "198.51.100.7"


def test_client_ip_handles_no_client() -> None:
    req = _make_request(xff=None, client_host=None)
    assert _client_ip(req) == "unknown"


# ---------- enforce_signup_rate_limit ----------


@pytest.mark.asyncio
async def test_disabled_when_not_multitenant() -> None:
    """Self-hosted (MULTI_TENANT=False) should never call Redis."""
    req = _make_request(client_host="1.2.3.4")
    fake_redis = MagicMock()
    with (
        patch.object(rl, "MULTI_TENANT", False),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ) as conn,
    ):
        await enforce_signup_rate_limit(req)
    conn.assert_not_awaited()


@pytest.mark.asyncio
async def test_allows_when_under_limit() -> None:
    """Counts at or below the hourly cap do not raise."""
    req = _make_request(client_host="1.2.3.4")
    fake_redis = MagicMock()
    fake_redis.incr = AsyncMock(return_value=_PER_IP_PER_HOUR)  # exactly at cap
    fake_redis.expire = AsyncMock()
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        await enforce_signup_rate_limit(req)


@pytest.mark.asyncio
async def test_rejects_when_over_limit() -> None:
    """Strictly above the cap → OnyxError.RATE_LIMITED (HTTP 429)."""
    req = _make_request(client_host="1.2.3.4")
    fake_redis = MagicMock()
    fake_redis.incr = AsyncMock(return_value=_PER_IP_PER_HOUR + 1)
    fake_redis.expire = AsyncMock()
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        with pytest.raises(OnyxError) as exc_info:
            await enforce_signup_rate_limit(req)
    assert exc_info.value.error_code.status_code == 429


@pytest.mark.asyncio
async def test_sets_ttl_only_on_first_hit() -> None:
    """Every non-first INCR must not reset the bucket TTL."""
    req = _make_request(client_host="1.2.3.4")
    fake_redis = MagicMock()
    fake_redis.incr = AsyncMock(return_value=3)  # not the first hit
    fake_redis.expire = AsyncMock()
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        await enforce_signup_rate_limit(req)
    fake_redis.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_fails_open_on_redis_error() -> None:
    """Redis blip must NOT block legitimate signups."""
    req = _make_request(client_host="1.2.3.4")
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(
            rl,
            "get_async_redis_connection",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ),
    ):
        # Does not raise.
        await enforce_signup_rate_limit(req)


def test_bucket_keys_differ_across_ips() -> None:
    """Two different IPs in the same hour must not share a counter."""
    a = _bucket_key("1.1.1.1")
    b = _bucket_key("2.2.2.2")
    assert a != b
    assert a.startswith("signup_rate:1.1.1.1:")
    assert b.startswith("signup_rate:2.2.2.2:")
