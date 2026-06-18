"""Unit tests for the reCAPTCHA Enterprise Assessment rejection ladder."""

from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.auth import captcha as captcha_module
from onyx.auth.captcha import CaptchaAction
from onyx.auth.captcha import CaptchaVerificationError
from onyx.auth.captcha import verify_captcha_token


def _fake_client(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _fresh_create_time() -> str:
    """An RFC3339 createTime that passes the 120s freshness check."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assessment(
    *,
    valid: bool = True,
    invalid_reason: str | None = None,
    action: str = "signup",
    hostname: str = "cloud.onyx.app",
    create_time: str | None = None,
    score: float = 0.9,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "name": "projects/154649423065/assessments/abc",
        "tokenProperties": {
            "valid": valid,
            "invalidReason": invalid_reason,
            "action": action,
            "hostname": hostname,
            "createTime": create_time or _fresh_create_time(),
        },
        "riskAnalysis": {"score": score, "reasons": reasons or []},
    }


@pytest.fixture(autouse=True)
def _test_env() -> Iterator[None]:
    """Stub the Redis replay cache (covered in test_captcha_replay.py) and
    populate cloud-like config so the hostname check actually fires."""
    with (
        patch.object(
            captcha_module,
            "_reserve_token_or_raise",
            AsyncMock(return_value=None),
        ),
        patch.object(captcha_module, "_release_token", AsyncMock(return_value=None)),
        patch.object(
            captcha_module,
            "RECAPTCHA_HOSTNAME_ALLOWLIST",
            frozenset({"cloud.onyx.app"}),
        ),
        patch.object(captcha_module, "RECAPTCHA_SCORE_THRESHOLD", 0.8),
    ):
        yield


@pytest.mark.asyncio
async def test_happy_path_passes() -> None:
    client = _fake_client(_assessment())
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_invalid_token_rejects_with_reason() -> None:
    client = _fake_client(_assessment(valid=False, invalid_reason="MALFORMED"))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="MALFORMED"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_hostname_mismatch_rejects() -> None:
    client = _fake_client(_assessment(hostname="evil.example.com"))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="hostname"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_stale_create_time_rejects() -> None:
    stale = "2020-01-01T00:00:00Z"
    client = _fake_client(_assessment(create_time=stale))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="token expired"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_action_mismatch_rejects_strictly() -> None:
    """A signup token cannot satisfy the oauth path and vice versa."""
    client = _fake_client(_assessment(action="oauth"))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="action mismatch"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_empty_action_rejects() -> None:
    """Regression guard: the legacy code skipped the check when action was
    falsy. Enterprise ladder must reject instead."""
    client = _fake_client(_assessment(action=""))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="action mismatch"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_automation_reason_rejects_even_with_high_score() -> None:
    """The key win of moving to Enterprise: a 0.9-scoring bot caught by
    reasons[] still gets rejected. Legacy siteverify would have let this
    through on score alone."""
    client = _fake_client(_assessment(score=0.9, reasons=["AUTOMATION"]))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="AUTOMATION"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_too_much_traffic_reason_rejects() -> None:
    client = _fake_client(_assessment(score=0.9, reasons=["TOO_MUCH_TRAFFIC"]))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="TOO_MUCH_TRAFFIC"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_unexpected_environment_reason_rejects() -> None:
    client = _fake_client(_assessment(score=0.9, reasons=["UNEXPECTED_ENVIRONMENT"]))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="UNEXPECTED_ENVIRONMENT"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_low_confidence_score_reason_rejects() -> None:
    client = _fake_client(_assessment(score=0.9, reasons=["LOW_CONFIDENCE_SCORE"]))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="LOW_CONFIDENCE_SCORE"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_suspected_carding_reason_rejects() -> None:
    client = _fake_client(_assessment(score=0.9, reasons=["SUSPECTED_CARDING"]))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="SUSPECTED_CARDING"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_score_below_floor_rejects() -> None:
    client = _fake_client(_assessment(score=0.1))
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="suspicious"):
            await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_soft_reason_alone_does_not_reject() -> None:
    """Reasons outside the hard-reject set (e.g. SUSPECTED_CHARGEBACK,
    UNEXPECTED_USAGE_PATTERNS) do not by themselves reject — if the score is
    above floor and nothing else fails, the request passes.
    """
    client = _fake_client(
        _assessment(
            score=0.9, reasons=["SUSPECTED_CHARGEBACK", "UNEXPECTED_USAGE_PATTERNS"]
        )
    )
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        await verify_captcha_token("tok", CaptchaAction.SIGNUP)


@pytest.mark.asyncio
async def test_no_op_when_disabled() -> None:
    """Disabled captcha returns None without making an HTTP call."""
    client = _fake_client(_assessment())
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=False),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        await verify_captcha_token("tok", CaptchaAction.SIGNUP)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_token_rejected_before_http() -> None:
    client = _fake_client(_assessment())
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        with pytest.raises(CaptchaVerificationError, match="required"):
            await verify_captcha_token("", CaptchaAction.SIGNUP)
    client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_body_has_enterprise_shape() -> None:
    client = _fake_client(_assessment())
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_module, "RECAPTCHA_ENTERPRISE_PROJECT_ID", "test-project"),
        patch.object(captcha_module, "RECAPTCHA_SITE_KEY", "test-site-key"),
        patch.object(captcha_module, "RECAPTCHA_ENTERPRISE_API_KEY", "test-api-key"),
        patch.object(captcha_module.httpx, "AsyncClient", return_value=client),
    ):
        await verify_captcha_token("tok", CaptchaAction.SIGNUP)

    client.post.assert_awaited_once()
    call = client.post.await_args
    assert call is not None
    url = call.args[0]
    assert url == (
        "https://recaptchaenterprise.googleapis.com/v1/projects/test-project/assessments"
    )
    body = call.kwargs["json"]
    assert body["event"] == {
        "token": "tok",
        "siteKey": "test-site-key",
        "expectedAction": "signup",
    }
    assert call.kwargs["params"] == {"key": "test-api-key"}
