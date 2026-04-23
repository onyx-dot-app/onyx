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


class CaptchaAction(StrEnum):
    """Distinct per-endpoint action names. Enforced against
    ``tokenProperties.action`` with strict equality so a token minted for
    one endpoint cannot be replayed against another."""

    SIGNUP = "signup"
    LOGIN = "login"
    OAUTH = "oauth"


class CaptchaVerificationError(Exception):
    """Raised when captcha verification fails."""


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
                "Captcha verification failed: token already used"
            )
    except CaptchaVerificationError:
        raise
    except Exception as e:
        logger.error(f"Captcha replay cache error (failing open): {e}")


async def _release_token(token: str) -> None:
    """Unclaim the reservation when the failure is OURS (transport, parse),
    not Google's. Google-rejected tokens stay claimed — they are dead for
    their whole TTL regardless."""
    try:
        redis = await get_async_redis_connection()
        await redis.delete(_replay_cache_key(token))
    except Exception as e:
        logger.error(f"Captcha replay cache release error (ignored): {e}")


def _check_token_freshness(create_time: str | None) -> None:
    if create_time is None:
        raise CaptchaVerificationError(
            "Captcha verification failed: missing createTime"
        )
    try:
        ts = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f"Captcha createTime unparseable: {create_time!r}")
        raise CaptchaVerificationError(
            "Captcha verification failed: malformed createTime"
        )
    age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    if age_seconds > _TOKEN_MAX_AGE_SECONDS:
        logger.warning(f"Captcha token stale: age={age_seconds:.1f}s")
        raise CaptchaVerificationError("Captcha verification failed: token expired")


def _evaluate_assessment(
    result: RecaptchaAssessmentResponse, action: CaptchaAction
) -> None:
    tp = result.token_properties
    ra = result.risk_analysis

    if not tp.valid:
        reason = tp.invalid_reason or "INVALID"
        logger.warning(f"Captcha token invalid: reason={reason}")
        raise CaptchaVerificationError(f"Captcha verification failed: {reason}")

    if RECAPTCHA_HOSTNAME_ALLOWLIST and (
        tp.hostname is None or tp.hostname not in RECAPTCHA_HOSTNAME_ALLOWLIST
    ):
        logger.warning(f"Captcha hostname mismatch: {tp.hostname!r}")
        raise CaptchaVerificationError("Captcha verification failed: hostname mismatch")

    _check_token_freshness(tp.create_time)

    if tp.action != action.value:
        logger.warning(
            f"Captcha action mismatch: got={tp.action!r} expected={action.value!r}"
        )
        raise CaptchaVerificationError("Captcha verification failed: action mismatch")

    hard = _HARD_REJECT_REASONS.intersection(ra.reasons)
    if hard:
        logger.warning(f"Captcha hard reject: reasons={sorted(hard)} score={ra.score}")
        raise CaptchaVerificationError(
            f"Captcha verification failed: {', '.join(sorted(hard))}"
        )

    if ra.score < RECAPTCHA_SCORE_THRESHOLD:
        logger.warning(
            f"Captcha score below threshold: {ra.score} < {RECAPTCHA_SCORE_THRESHOLD} reasons={ra.reasons}"
        )
        raise CaptchaVerificationError(
            "Captcha verification failed: suspicious activity detected"
        )

    logger.info(
        f"Captcha verification passed: action={tp.action} score={ra.score} reasons={ra.reasons} hostname={tp.hostname}"
    )


async def verify_captcha_token(token: str, action: CaptchaAction) -> None:
    """Reject on any of: empty token, replay, invalid token, hostname
    mismatch, stale createTime, action mismatch, hard-reject reason, or
    score below threshold. No silent skip on null/empty fields."""
    if not is_captcha_enabled():
        return

    if not token:
        raise CaptchaVerificationError("Captcha token is required")

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
        logger.error(f"Captcha verification failed unexpectedly: {e}")
        await _release_token(token)
        raise CaptchaVerificationError("Captcha verification service unavailable")


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
