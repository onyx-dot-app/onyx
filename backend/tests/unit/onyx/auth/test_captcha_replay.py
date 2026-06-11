"""Unit tests for the reCAPTCHA token replay cache."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.auth import captcha as captcha_module
from onyx.auth.captcha import _replay_cache_key
from onyx.auth.captcha import _reserve_token_or_raise
from onyx.auth.captcha import CaptchaAction
from onyx.auth.captcha import CaptchaVerificationError
from onyx.auth.captcha import verify_captcha_token


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


@pytest.mark.asyncio
async def test_reservation_released_when_google_unreachable() -> None:
    """If the Assessment API itself errors (our side, not the token's), the
    replay reservation must be released so the user can retry with the same
    still-valid token instead of getting 'already used' for 120s."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    fake_redis.delete = AsyncMock(return_value=1)

    fake_client = MagicMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("network down"))
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
        with pytest.raises(CaptchaVerificationError, match="service unavailable"):
            await verify_captcha_token("valid-token", CaptchaAction.SIGNUP)

    # The reservation was claimed and then released.
    fake_redis.set.assert_awaited_once()
    fake_redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_reservation_released_on_unexpected_response_shape() -> None:
    """Non-HTTP errors during response parsing (malformed JSON, pydantic
    validation failure) also release the reservation — they mean WE couldn't
    verify the token, not that the token is definitively invalid."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    fake_redis.delete = AsyncMock(return_value=1)

    fake_httpx_response = MagicMock()
    fake_httpx_response.raise_for_status = MagicMock()
    fake_httpx_response.json = MagicMock(side_effect=ValueError("not valid JSON"))
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
        with pytest.raises(CaptchaVerificationError, match="service unavailable"):
            await verify_captcha_token("valid-token", CaptchaAction.SIGNUP)

    fake_redis.set.assert_awaited_once()
    fake_redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_reservation_kept_when_google_rejects_token() -> None:
    """If Google itself says the token is invalid (tokenProperties.valid=false),
    the reservation must NOT be released — that token is known-bad for its
    entire lifetime and shouldn't be retryable."""
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    fake_redis.delete = AsyncMock(return_value=1)

    fake_httpx_response = MagicMock()
    fake_httpx_response.raise_for_status = MagicMock()
    fake_httpx_response.json = MagicMock(
        return_value={
            "name": "projects/154649423065/assessments/abc",
            "tokenProperties": {
                "valid": False,
                "invalidReason": "MALFORMED",
            },
            "riskAnalysis": {"score": 0.0, "reasons": []},
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
        with pytest.raises(CaptchaVerificationError, match="MALFORMED"):
            await verify_captcha_token("bad-token", CaptchaAction.SIGNUP)

    fake_redis.set.assert_awaited_once()
    fake_redis.delete.assert_not_awaited()
