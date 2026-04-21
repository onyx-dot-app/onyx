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


def _fake_pipeline_redis(incr_return: int) -> MagicMock:
    """Build a Redis mock whose pipeline().execute() yields [incr_return, ok]."""
    pipeline = MagicMock()
    pipeline.incr = MagicMock()
    pipeline.expire = MagicMock()
    pipeline.execute = AsyncMock(return_value=[incr_return, 1])
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=pipeline)
    redis._pipeline = pipeline  # type: ignore[attr-defined]
    return redis


def test_client_ip_uses_leftmost_when_first_entry_is_public() -> None:
    req = _make_request(xff="1.2.3.4, 10.0.0.42")
    assert _client_ip(req) == "1.2.3.4"


def test_client_ip_falls_back_when_leftmost_is_private() -> None:
    req = _make_request(xff="10.0.0.1, 1.2.3.4", client_host="5.6.7.8")
    assert _client_ip(req) == "5.6.7.8"


def test_client_ip_falls_back_when_leftmost_is_loopback() -> None:
    req = _make_request(xff="127.0.0.1", client_host="5.6.7.8")
    assert _client_ip(req) == "5.6.7.8"


def test_client_ip_falls_back_when_xff_is_malformed() -> None:
    req = _make_request(xff="not-an-ip, 1.2.3.4", client_host="10.0.0.1")
    assert _client_ip(req) == "10.0.0.1"


def test_client_ip_falls_back_to_tcp_peer_when_xff_absent() -> None:
    req = _make_request(xff=None, client_host="5.6.7.8")
    assert _client_ip(req) == "5.6.7.8"


def test_client_ip_handles_no_client() -> None:
    req = _make_request(xff=None, client_host=None)
    assert _client_ip(req) == "unknown"


@pytest.mark.asyncio
async def test_disabled_when_not_multitenant() -> None:
    req = _make_request(client_host="1.2.3.4")
    fake_redis = MagicMock()
    with (
        patch.object(rl, "MULTI_TENANT", False),
        patch.object(rl, "SIGNUP_RATE_LIMIT_ENABLED", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ) as conn,
    ):
        await enforce_signup_rate_limit(req)
    conn.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_when_enable_flag_off() -> None:
    req = _make_request(client_host="1.2.3.4")
    fake_redis = MagicMock()
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(rl, "SIGNUP_RATE_LIMIT_ENABLED", False),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ) as conn,
    ):
        await enforce_signup_rate_limit(req)
    conn.assert_not_awaited()


@pytest.mark.asyncio
async def test_allows_when_under_limit() -> None:
    """Counts at or below the hourly cap do not raise."""
    req = _make_request(xff="1.2.3.4, 10.0.0.1")
    fake_redis = _fake_pipeline_redis(incr_return=_PER_IP_PER_HOUR)
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(rl, "SIGNUP_RATE_LIMIT_ENABLED", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        await enforce_signup_rate_limit(req)


@pytest.mark.asyncio
async def test_rejects_when_over_limit() -> None:
    """Strictly above the cap → OnyxError.RATE_LIMITED (HTTP 429)."""
    req = _make_request(xff="1.2.3.4, 10.0.0.1")
    fake_redis = _fake_pipeline_redis(incr_return=_PER_IP_PER_HOUR + 1)
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(rl, "SIGNUP_RATE_LIMIT_ENABLED", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        with pytest.raises(OnyxError) as exc_info:
            await enforce_signup_rate_limit(req)
    assert exc_info.value.error_code.status_code == 429


@pytest.mark.asyncio
async def test_pipeline_expire_runs_on_every_hit() -> None:
    """INCR and EXPIRE run in a single pipeline for atomicity."""
    req = _make_request(xff="1.2.3.4, 10.0.0.1")
    fake_redis = _fake_pipeline_redis(incr_return=3)
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(rl, "SIGNUP_RATE_LIMIT_ENABLED", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        await enforce_signup_rate_limit(req)
    fake_redis._pipeline.expire.assert_called_once()


@pytest.mark.asyncio
async def test_fails_open_on_redis_error() -> None:
    """Redis blip must NOT block legitimate signups."""
    req = _make_request(xff="1.2.3.4, 10.0.0.1")
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(rl, "SIGNUP_RATE_LIMIT_ENABLED", True),
        patch.object(
            rl,
            "get_async_redis_connection",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ),
    ):
        await enforce_signup_rate_limit(req)


def test_bucket_keys_differ_across_ips() -> None:
    """Two different IPs in the same hour must not share a counter."""
    a = _bucket_key("1.1.1.1")
    b = _bucket_key("2.2.2.2")
    assert a != b
    assert a.startswith("signup_rate:1.1.1.1:")
    assert b.startswith("signup_rate:2.2.2.2:")
