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
    # Stash the pipeline for assertions
    redis._pipeline = pipeline  # type: ignore[attr-defined]
    return redis


# ---------- IP extraction ----------


def test_client_ip_picks_entry_written_by_outermost_trusted_proxy() -> None:
    """With 2 trusted proxies (ALB + nginx), XFF looks like
    ``<client-prefix>, real-client-ip, alb-ip``. Take the second-to-last,
    NOT the leftmost (which is attacker-controlled)."""
    req = _make_request(
        xff="spoofed-by-bot, 198.51.100.99, 10.0.0.1",
    )
    assert _client_ip(req) == "198.51.100.99"


def test_client_ip_ignores_client_controlled_prefix() -> None:
    """A bot-prepended entry at the start of XFF must never be used."""
    req = _make_request(xff="99.99.99.99, 203.0.113.7, 10.0.0.1")
    # With _TRUSTED_PROXY_HOPS=2 the outermost trusted hop wrote
    # 203.0.113.7; the attacker's 99.99.99.99 is ignored.
    assert _client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_tcp_peer_when_xff_too_short() -> None:
    """If the XFF chain is shorter than the expected trust depth, we don't
    trust any of it — fall through to the TCP peer."""
    req = _make_request(xff="only-one-entry", client_host="198.51.100.7")
    assert _client_ip(req) == "198.51.100.7"


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
    fake_redis = _fake_pipeline_redis(incr_return=_PER_IP_PER_HOUR)
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
    fake_redis = _fake_pipeline_redis(incr_return=_PER_IP_PER_HOUR + 1)
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
async def test_pipeline_expire_runs_on_every_hit() -> None:
    """INCR and EXPIRE must go through the same pipeline so the TTL is
    set atomically — even on the 2nd, 3rd, ... hit. This closes the
    'key with no TTL → permanent block' class of bugs."""
    req = _make_request(client_host="1.2.3.4")
    fake_redis = _fake_pipeline_redis(incr_return=3)
    with (
        patch.object(rl, "MULTI_TENANT", True),
        patch.object(
            rl, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
        ),
    ):
        await enforce_signup_rate_limit(req)
    # EXPIRE is always queued into the pipeline — no branch on count == 1.
    fake_redis._pipeline.expire.assert_called_once()


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
