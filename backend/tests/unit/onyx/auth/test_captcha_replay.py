"""Unit tests for the reCAPTCHA token replay cache."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.auth import captcha as captcha_module
from onyx.auth.captcha import _replay_cache_key
from onyx.auth.captcha import _reserve_token_or_raise
from onyx.auth.captcha import CaptchaVerificationError


@pytest.mark.asyncio
async def test_reserve_token_succeeds_on_first_use() -> None:
    """First SETNX claims the token; no exception."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    with patch.object(
        captcha_module,
        "get_async_redis_connection",
        AsyncMock(return_value=fake_redis),
    ):
        await _reserve_token_or_raise("some-token")
    fake_redis.set.assert_awaited_once()
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
        captcha_module,
        "get_async_redis_connection",
        AsyncMock(return_value=fake_redis),
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
