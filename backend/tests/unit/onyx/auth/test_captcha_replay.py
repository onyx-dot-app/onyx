"""Unit tests for the reCAPTCHA token replay cache + require-score check."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.auth import captcha as captcha_module
from onyx.auth.captcha import _replay_cache_key
from onyx.auth.captcha import _reserve_token_or_raise
from onyx.auth.captcha import CaptchaVerificationError
from onyx.auth.captcha import verify_captcha_token


# ---------- replay cache ----------


@pytest.mark.asyncio
async def test_reserve_token_succeeds_on_first_use() -> None:
    """First SETNX claims the token; no exception."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    with patch.object(
        captcha_module, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
    ):
        await _reserve_token_or_raise("some-token")
    fake_redis.set.assert_awaited_once()
    # Verify SETNX + TTL args went through.
    await_args = fake_redis.set.await_args
    assert await_args is not None
    assert await_args.kwargs["nx"] is True
    assert await_args.kwargs["ex"] == 120


@pytest.mark.asyncio
async def test_reserve_token_rejects_replay() -> None:
    """Second use of the same token within TTL → CaptchaVerificationError."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=False)
    with patch.object(
        captcha_module, "get_async_redis_connection", AsyncMock(return_value=fake_redis)
    ):
        with pytest.raises(CaptchaVerificationError, match="token already used"):
            await _reserve_token_or_raise("replayed-token")


@pytest.mark.asyncio
async def test_reserve_token_fails_open_on_redis_error() -> None:
    """A Redis blip must NOT block legitimate registrations."""
    with patch.object(
        captcha_module,
        "get_async_redis_connection",
        AsyncMock(side_effect=RuntimeError("redis down")),
    ):
        # No exception raised — replay protection is gracefully skipped.
        await _reserve_token_or_raise("any-token")


def test_replay_cache_key_is_sha256_prefixed() -> None:
    """The stored key never contains the raw token."""
    key = _replay_cache_key("raw-value")
    assert key.startswith("captcha:replay:")
    assert "raw-value" not in key
    # Length = prefix + 64 hex chars.
    assert len(key) == len("captcha:replay:") + 64


# ---------- require-score check ----------


@pytest.mark.asyncio
async def test_verify_rejects_when_score_missing() -> None:
    """A siteverify response with no score field is rejected outright —
    closes the accidental 'test secret in prod' bypass path."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)

    fake_httpx_response = MagicMock()
    fake_httpx_response.raise_for_status = MagicMock()
    fake_httpx_response.json = MagicMock(
        return_value={"success": True, "hostname": "testkey.google.com"}
    )
    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_httpx_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_module,
            "get_async_redis_connection",
            AsyncMock(return_value=fake_redis),
        ),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=fake_client),
    ):
        with pytest.raises(CaptchaVerificationError, match="missing score"):
            await verify_captcha_token("test-token", expected_action="signup")


@pytest.mark.asyncio
async def test_verify_accepts_when_score_present_and_above_threshold() -> None:
    """Sanity check the happy path still works with the tighter score rule."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)

    fake_httpx_response = MagicMock()
    fake_httpx_response.raise_for_status = MagicMock()
    fake_httpx_response.json = MagicMock(
        return_value={
            "success": True,
            "score": 0.9,
            "action": "signup",
            "hostname": "cloud.onyx.app",
        }
    )
    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_httpx_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_module,
            "get_async_redis_connection",
            AsyncMock(return_value=fake_redis),
        ),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=fake_client),
    ):
        # Should not raise.
        await verify_captcha_token("fresh-token", expected_action="signup")
