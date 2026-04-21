"""Unit tests for the require-score check in verify_captcha_token."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.auth import captcha as captcha_module
from onyx.auth.captcha import CaptchaVerificationError
from onyx.auth.captcha import verify_captcha_token


def _fake_httpx_client_returning(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_rejects_when_score_missing() -> None:
    """Siteverify response with no score field is rejected outright —
    closes the accidental 'test secret in prod' bypass path."""
    client = _fake_httpx_client_returning(
        {"success": True, "hostname": "testkey.google.com"}
    )
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="missing score"):
            await verify_captcha_token("test-token", expected_action="signup")


@pytest.mark.asyncio
async def test_accepts_when_score_present_and_above_threshold() -> None:
    """Sanity check the happy path still works with the tighter score rule."""
    client = _fake_httpx_client_returning(
        {
            "success": True,
            "score": 0.9,
            "action": "signup",
            "hostname": "cloud.onyx.app",
        }
    )
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        # Should not raise.
        await verify_captcha_token("fresh-token", expected_action="signup")


@pytest.mark.asyncio
async def test_rejects_when_score_below_threshold() -> None:
    """A score present but below threshold still rejects (existing behavior,
    guarding against regression from this PR's restructure)."""
    client = _fake_httpx_client_returning(
        {
            "success": True,
            "score": 0.1,
            "action": "signup",
            "hostname": "cloud.onyx.app",
        }
    )
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(
            CaptchaVerificationError, match="suspicious activity detected"
        ):
            await verify_captcha_token("low-score-token", expected_action="signup")
