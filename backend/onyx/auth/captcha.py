"""Captcha verification for user registration.

Two flows share this module:

1. Email/password signup — ``UserManager.create`` verifies the token
   posted with the signup body.
2. Google OAuth signup — the frontend pre-verifies a token, the backend
   sets a signed cookie, and ``CaptchaCookieMiddleware`` checks the
   cookie on the ``/auth/oauth/callback`` redirect.

Verification calls the reCAPTCHA Enterprise Assessment API so rejections
can key on ``riskAnalysis.reasons`` rather than a raw 0-1 score.
``issue_captcha_cookie_value`` / ``validate_captcha_cookie_value`` sign
the OAuth cookie.
"""

import hashlib
import hmac
import time
from datetime import datetime
from datetime import timezone
from enum import StrEnum

import httpx
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import CAPTCHA_COOKIE_TTL_SECONDS
from onyx.configs.app_configs import CAPTCHA_ENABLED
from onyx.configs.app_configs import RECAPTCHA_ENTERPRISE_API_KEY
from onyx.configs.app_configs import RECAPTCHA_ENTERPRISE_PROJECT_ID
from onyx.configs.app_configs import RECAPTCHA_HOSTNAME_ALLOWLIST
from onyx.configs.app_configs import RECAPTCHA_SCORE_THRESHOLD
from onyx.configs.app_configs import RECAPTCHA_SITE_KEY
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.metrics.captcha_metrics import record_captcha_failure
from onyx.server.metrics.captcha_metrics import record_captcha_flaky_recovery
from onyx.server.metrics.captcha_metrics import record_captcha_success
from onyx.utils.client_ip import current_client_ip
from onyx.utils.logger import setup_logger

logger = setup_logger()

CAPTCHA_COOKIE_NAME = "onyx_captcha_verified"

# Enterprise Assessment reason enums defined by Google — not a
# per-deployment tuning knob. Any of these reasons on a token means the
# risk signal is strong enough to reject outright regardless of the
# numeric score.
_HARD_REJECT_REASONS: frozenset[str] = frozenset(
    {
        "AUTOMATION",
        "UNEXPECTED_ENVIRONMENT",
        "TOO_MUCH_TRAFFIC",
        "LOW_CONFIDENCE_SCORE",
        "SUSPECTED_CARDING",
    }
)

# Matches Google's own ~2 minute token validity window.
_TOKEN_MAX_AGE_SECONDS = 120

_REPLAY_CACHE_TTL_SECONDS = 120
_REPLAY_KEY_PREFIX = "captcha:replay:"

# Window after a failure during which a subsequent success by the same
# individual is counted as a "flaky" recovery. Longer than the token
# freshness window since a real user may retry minutes after being bounced.
_FLAKY_FAIL_TTL_SECONDS = 3600
_FLAKY_KEY_PREFIX = "captcha:recent_fail:"


class CaptchaAction(StrEnum):
    """Distinct per-endpoint action names. Enforced against
    ``tokenProperties.action`` with strict equality so a token minted for
    one endpoint cannot be replayed against another."""

    SIGNUP = "signup"
    LOGIN = "login"
    OAUTH = "oauth"


class CaptchaVerificationError(Exception):
    """Raised when captcha verification fails. ``reason`` is a bounded,
    low-cardinality category used as a Prometheus label (see
    ``onyx/server/metrics/captcha_metrics.py``)."""

    def __init__(self, message: str, reason: str = "unknown") -> None:
        super().__init__(message)
        self.reason = reason


class _TokenProperties(BaseModel):
    valid: bool = False
    invalid_reason: str | None = Field(default=None, alias="invalidReason")
    action: str | None = None
    hostname: str | None = None
    create_time: str | None = Field(default=None, alias="createTime")


class _RiskAnalysis(BaseModel):
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class RecaptchaAssessmentResponse(BaseModel):
    name: str | None = None
    token_properties: _TokenProperties = Field(
        default_factory=_TokenProperties, alias="tokenProperties"
    )
    risk_analysis: _RiskAnalysis = Field(
        default_factory=_RiskAnalysis, alias="riskAnalysis"
    )


def is_captcha_enabled() -> bool:
    return (
        CAPTCHA_ENABLED
        and bool(RECAPTCHA_ENTERPRISE_PROJECT_ID)
        and bool(RECAPTCHA_ENTERPRISE_API_KEY)
        and bool(RECAPTCHA_SITE_KEY)
    )


def _replay_cache_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_REPLAY_KEY_PREFIX}{digest}"


async def _reserve_token_or_raise(token: str) -> None:
    """Claim a token fingerprint via ``SETNX``. A concurrent replay within
    the TTL returns False → raise. Redis errors fail open so a blip does
    not block legitimate signups."""
    try:
        redis = await get_async_redis_connection()
        claimed = await redis.set(
            _replay_cache_key(token),
            "1",
            nx=True,
            ex=_REPLAY_CACHE_TTL_SECONDS,
        )
        if not claimed:
            logger.warning("Captcha replay detected: token already used")
            raise CaptchaVerificationError(
                "Captcha verification failed: token already used", reason="replay"
            )
    except CaptchaVerificationError:
        raise
    except Exception as e:
        logger.error("Captcha replay cache error (failing open): %s", e)


async def _release_token(token: str) -> None:
    """Unclaim the reservation when the failure is OURS (transport, parse),
    not Google's. Google-rejected tokens stay claimed — they are dead for
    their whole TTL regardless."""
    try:
        redis = await get_async_redis_connection()
        await redis.delete(_replay_cache_key(token))
    except Exception as e:
        logger.error("Captcha replay cache release error (ignored): %s", e)


def _flaky_state_key(action: CaptchaAction, individual: str) -> str:
    """HMAC the (action, individual) pair so the raw client IP is never stored
    in Redis and the low-entropy value cannot be trivially recovered."""
    digest = hmac.new(
        _flaky_state_signing_key(),
        f"{action.value}:{individual}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{_FLAKY_KEY_PREFIX}{digest}"


def _flaky_state_signing_key() -> bytes:
    return hashlib.sha256(
        f"onyx-captcha-flaky-v1::{USER_AUTH_SECRET}".encode("utf-8")
    ).digest()


async def _note_failure_for_flaky_tracking(action: CaptchaAction) -> None:
    """Mark that the current individual just failed so a later success can be
    counted as flaky. Keyed by client IP — the only identifier available across
    all three flows. No IP (e.g. outside a request) → nothing to attribute."""
    individual = current_client_ip()
    if not individual:
        return
    try:
        redis = await get_async_redis_connection()
        await redis.set(
            _flaky_state_key(action, individual), "1", ex=_FLAKY_FAIL_TTL_SECONDS
        )
    except Exception as e:
        logger.debug("Captcha flaky-state write failed (ignored): %s", e)


async def _consume_flaky_recovery(action: CaptchaAction) -> bool:
    """On success, return True (and clear the marker) if this individual failed
    within the flaky window. The delete makes it one-shot: one recovery is
    counted per fail→pass transition, not per subsequent success."""
    individual = current_client_ip()
    if not individual:
        return False
    try:
        redis = await get_async_redis_connection()
        deleted = await redis.delete(_flaky_state_key(action, individual))
        return bool(deleted)
    except Exception as e:
        logger.debug("Captcha flaky-state read failed (ignored): %s", e)
        return False


def _check_token_freshness(create_time: str | None) -> None:
    if create_time is None:
        raise CaptchaVerificationError(
            "Captcha verification failed: missing createTime",
            reason="missing_create_time",
        )
    try:
        ts = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Captcha createTime unparseable: %r", create_time)
        raise CaptchaVerificationError(
            "Captcha verification failed: malformed createTime",
            reason="malformed_create_time",
        )
    age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    if age_seconds > _TOKEN_MAX_AGE_SECONDS:
        logger.warning("Captcha token stale: age=%ss", format(age_seconds, ".1f"))
        raise CaptchaVerificationError(
            "Captcha verification failed: token expired", reason="expired"
        )


def _evaluate_assessment(
    result: RecaptchaAssessmentResponse, action: CaptchaAction
) -> None:
    tp = result.token_properties
    ra = result.risk_analysis

    if not tp.valid:
        reason = tp.invalid_reason or "INVALID"
        logger.warning("Captcha token invalid: reason=%s", reason)
        raise CaptchaVerificationError(
            f"Captcha verification failed: {reason}", reason="invalid_token"
        )

    if RECAPTCHA_HOSTNAME_ALLOWLIST and (
        tp.hostname is None or tp.hostname not in RECAPTCHA_HOSTNAME_ALLOWLIST
    ):
        logger.warning("Captcha hostname mismatch: %r", tp.hostname)
        raise CaptchaVerificationError(
            "Captcha verification failed: hostname mismatch",
            reason="hostname_mismatch",
        )

    _check_token_freshness(tp.create_time)

    if tp.action != action.value:
        logger.warning(
            "Captcha action mismatch: got=%r expected=%r", tp.action, action.value
        )
        raise CaptchaVerificationError(
            "Captcha verification failed: action mismatch", reason="action_mismatch"
        )

    hard = _HARD_REJECT_REASONS.intersection(ra.reasons)
    if hard:
        logger.warning(
            "Captcha hard reject: reasons=%s score=%s", sorted(hard), ra.score
        )
        raise CaptchaVerificationError(
            f"Captcha verification failed: {', '.join(sorted(hard))}",
            reason="hard_reject",
        )

    if ra.score < RECAPTCHA_SCORE_THRESHOLD:
        logger.warning(
            "Captcha score below threshold: %s < %s reasons=%s",
            ra.score,
            RECAPTCHA_SCORE_THRESHOLD,
            ra.reasons,
        )
        raise CaptchaVerificationError(
            "Captcha verification failed: suspicious activity detected",
            reason="low_score",
        )

    logger.info(
        "Captcha verification passed: action=%s score=%s reasons=%s hostname=%s",
        tp.action,
        ra.score,
        ra.reasons,
        tp.hostname,
    )


async def verify_captcha_token(token: str, action: CaptchaAction) -> None:
    """Reject on any of: empty token, replay, invalid token, hostname
    mismatch, stale createTime, action mismatch, hard-reject reason, or
    score below threshold. No silent skip on null/empty fields."""
    if not is_captcha_enabled():
        return

    try:
        if not token:
            raise CaptchaVerificationError(
                "Captcha token is required", reason="missing_token"
            )

        # Claim before the Google round-trip so a concurrent replay of the
        # same token is rejected without both callers hitting the API.
        await _reserve_token_or_raise(token)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    (
                        f"https://recaptchaenterprise.googleapis.com/v1/projects/{RECAPTCHA_ENTERPRISE_PROJECT_ID}/assessments"
                    ),
                    params={"key": RECAPTCHA_ENTERPRISE_API_KEY},
                    json={
                        "event": {
                            "token": token,
                            "siteKey": RECAPTCHA_SITE_KEY,
                            "expectedAction": action.value,
                        }
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                result = RecaptchaAssessmentResponse(**response.json())
                _evaluate_assessment(result, action)

        except CaptchaVerificationError:
            raise
        except Exception as e:
            logger.error("Captcha verification failed unexpectedly: %s", e)
            await _release_token(token)
            raise CaptchaVerificationError(
                "Captcha verification service unavailable",
                reason="service_unavailable",
            )
    except CaptchaVerificationError as err:
        record_captcha_failure(action.value, err.reason)
        await _note_failure_for_flaky_tracking(action)
        raise

    record_captcha_success(action.value)
    if await _consume_flaky_recovery(action):
        record_captcha_flaky_recovery(action.value)
        logger.info(
            "Captcha flaky recovery: action=%s passed after a recent failure",
            action.value,
        )


def _cookie_signing_key() -> bytes:
    return hashlib.sha256(
        f"onyx-captcha-cookie-v1::{USER_AUTH_SECRET}".encode("utf-8")
    ).digest()


def issue_captcha_cookie_value(now: int | None = None) -> str:
    """Return ``<expiry_epoch>.<hex_hmac>`` proving a recent captcha challenge."""
    issued_at = now if now is not None else int(time.time())
    expiry = issued_at + CAPTCHA_COOKIE_TTL_SECONDS
    sig = hmac.new(
        _cookie_signing_key(), str(expiry).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{expiry}.{sig}"


def validate_captcha_cookie_value(value: str | None) -> bool:
    if not value:
        return False
    parts = value.split(".", 1)
    if len(parts) != 2:
        return False
    expiry_str, provided_sig = parts
    try:
        expiry = int(expiry_str)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    expected_sig = hmac.new(
        _cookie_signing_key(), str(expiry).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_sig, provided_sig)
