"""Unit tests for reCAPTCHA Prometheus metrics, focused on the "flaky"
fail-then-pass recovery signal."""

from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from prometheus_client import Counter

from onyx.auth import captcha as captcha_module
from onyx.auth.captcha import CaptchaAction
from onyx.auth.captcha import CaptchaVerificationError
from onyx.auth.captcha import verify_captcha_token
from onyx.server.metrics import captcha_metrics


class _FakeRedis:
    """Minimal dict-backed async Redis supporting the SETNX + delete surface
    used by the replay cache and the flaky-state helpers."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, **_: object) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        if key in self.store:
            del self.store[key]
            return 1
        return 0


def _assessment(*, score: float = 0.9) -> dict[str, Any]:
    return {
        "name": "projects/154649423065/assessments/abc",
        "tokenProperties": {
            "valid": True,
            "invalidReason": None,
            "action": "login",
            "hostname": "cloud.onyx.app",
            "createTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "riskAnalysis": {"score": score, "reasons": []},
    }


def _fake_client(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _value(counter: Counter, **labels: str) -> float:
    return counter.labels(**labels)._value.get()


@pytest.fixture
def fake_redis() -> Iterator[None]:
    """Enable captcha and back it with a single shared fake Redis so state set
    by one verification call is visible to the next (mirrors the real
    cross-request behavior). Client IP is fixed so flaky tracking can attribute."""
    redis = _FakeRedis()
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_module,
            "get_async_redis_connection",
            AsyncMock(return_value=redis),
        ),
        patch.object(captcha_module, "current_client_ip", return_value="203.0.113.7"),
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_redis")
async def test_success_records_success_metric() -> None:
    before = _value(
        captcha_metrics.CAPTCHA_VERIFICATIONS, action="login", outcome="success"
    )
    with patch.object(
        captcha_module.httpx, "AsyncClient", return_value=_fake_client(_assessment())
    ):
        await verify_captcha_token("tok-ok", CaptchaAction.LOGIN)
    after = _value(
        captcha_metrics.CAPTCHA_VERIFICATIONS, action="login", outcome="success"
    )
    assert after == before + 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_redis")
async def test_failure_records_failure_metric_with_reason() -> None:
    fail_before = _value(
        captcha_metrics.CAPTCHA_FAILURES, action="login", reason="low_score"
    )
    outcome_before = _value(
        captcha_metrics.CAPTCHA_VERIFICATIONS, action="login", outcome="failure"
    )
    with patch.object(
        captcha_module.httpx,
        "AsyncClient",
        return_value=_fake_client(_assessment(score=0.1)),
    ):
        with pytest.raises(CaptchaVerificationError):
            await verify_captcha_token("tok-low", CaptchaAction.LOGIN)
    assert (
        _value(captcha_metrics.CAPTCHA_FAILURES, action="login", reason="low_score")
        == fail_before + 1
    )
    assert (
        _value(captcha_metrics.CAPTCHA_VERIFICATIONS, action="login", outcome="failure")
        == outcome_before + 1
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_redis")
async def test_flaky_recovery_counted_once_on_fail_then_pass() -> None:
    """An individual that fails and then passes increments the flaky counter
    exactly once — a second pass does not double-count."""
    before = _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login")

    # 1) Fail — leaves a recent-fail marker for this individual.
    with patch.object(
        captcha_module.httpx,
        "AsyncClient",
        return_value=_fake_client(_assessment(score=0.1)),
    ):
        with pytest.raises(CaptchaVerificationError):
            await verify_captcha_token("tok-fail", CaptchaAction.LOGIN)
    assert _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login") == before

    # 2) Pass — consumes the marker → flaky recovery.
    with patch.object(
        captcha_module.httpx, "AsyncClient", return_value=_fake_client(_assessment())
    ):
        await verify_captcha_token("tok-pass-1", CaptchaAction.LOGIN)
    assert (
        _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login") == before + 1
    )

    # 3) Second pass — marker already consumed → no further increment.
    with patch.object(
        captcha_module.httpx, "AsyncClient", return_value=_fake_client(_assessment())
    ):
        await verify_captcha_token("tok-pass-2", CaptchaAction.LOGIN)
    assert (
        _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login") == before + 1
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_redis")
async def test_clean_pass_is_not_flaky() -> None:
    """A first-try success with no prior failure is not a flaky recovery."""
    before = _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login")
    with patch.object(
        captcha_module.httpx, "AsyncClient", return_value=_fake_client(_assessment())
    ):
        await verify_captcha_token("tok-clean", CaptchaAction.LOGIN)
    assert _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login") == before


@pytest.mark.asyncio
async def test_flaky_tracking_skipped_without_client_ip() -> None:
    """No client IP (e.g. outside a request) → nothing to attribute, so a
    fail then pass is not counted as flaky."""
    redis = _FakeRedis()
    with (
        patch.object(captcha_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_module,
            "get_async_redis_connection",
            AsyncMock(return_value=redis),
        ),
        patch.object(captcha_module, "current_client_ip", return_value=None),
    ):
        before = _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login")
        with patch.object(
            captcha_module.httpx,
            "AsyncClient",
            return_value=_fake_client(_assessment(score=0.1)),
        ):
            with pytest.raises(CaptchaVerificationError):
                await verify_captcha_token("tok-fail", CaptchaAction.LOGIN)
        with patch.object(
            captcha_module.httpx,
            "AsyncClient",
            return_value=_fake_client(_assessment()),
        ):
            await verify_captcha_token("tok-pass", CaptchaAction.LOGIN)
        assert (
            _value(captcha_metrics.CAPTCHA_FLAKY_RECOVERIES, action="login") == before
        )
