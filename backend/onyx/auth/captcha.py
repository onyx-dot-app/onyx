"""Captcha verification for user registration.

Two flows share this module:

1. Email/password signup. The token is posted with the signup body and
   verified inline by ``UserManager.create``.

2. Google OAuth signup. The OAuth callback request originates from Google
   as a browser redirect, so we cannot attach a header or body field to it
   at that moment. Instead the frontend verifies a reCAPTCHA token BEFORE
   redirecting to Google and we set a signed HttpOnly cookie. The cookie
   is sent automatically on the callback request, where middleware checks
   it. ``issue_captcha_cookie_value`` / ``validate_captcha_cookie_value``
   handle the HMAC signing + expiry.

Verification calls the reCAPTCHA Enterprise Assessment API (not the
legacy ``siteverify`` endpoint) so rejections can key on
``riskAnalysis.reasons[]`` — Google's structured bot signals — instead
of a raw 0-1 score that sophisticated farms routinely clear.
"""

import hashlib
import hmac
import os
import time
from datetime import datetime
from datetime import timezone
from enum import StrEnum

import httpx
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import CAPTCHA_COOKIE_TTL_SECONDS
from onyx.configs.app_configs import CAPTCHA_ENABLED
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger

logger = setup_logger()

CAPTCHA_COOKIE_NAME = "onyx_captcha_verified"

# --- Enterprise Assessment wiring ------------------------------------------
# Project + site key are public, never rotate, and are Onyx-cloud-specific
# identifiers — hardcoding keeps them out of app_configs without losing
# clarity. Only the API key is a secret, consumed from the environment.
_RECAPTCHA_PROJECT_ID = "danswer-404504"
# pragma: allowlist nextline secret — reCAPTCHA SITE keys are public (served to
# the browser inside HTML) despite the `6L…` prefix that ripsecrets flags.
_RECAPTCHA_SITE_KEY = (
    "6Ldb7WosAAAAAGsxnaOHHjw34afhnyuy9VhQ4UaZ"  # pragma: allowlist secret
)
_RECAPTCHA_ENTERPRISE_API_KEY = os.environ.get("RECAPTCHA_ENTERPRISE_API_KEY", "")
_RECAPTCHA_ASSESSMENT_URL = f"https://recaptchaenterprise.googleapis.com/v1/projects/{_RECAPTCHA_PROJECT_ID}/assessments"

# Policy values — the knobs that would have been env vars in a v3-only world.
# Score is a grey-area floor; reasons[] are the primary kill signal.
_HOSTNAME_ALLOWLIST: frozenset[str] = frozenset({"cloud.onyx.app"})
_HARD_REJECT_REASONS: frozenset[str] = frozenset(
    {"AUTOMATION", "UNEXPECTED_ENVIRONMENT", "TOO_MUCH_TRAFFIC"}
)
_TOKEN_MAX_AGE_SECONDS = 120
_SCORE_FLOOR = 0.5

# --- Replay cache (unchanged from #10402) ----------------------------------
_REPLAY_CACHE_TTL_SECONDS = 120
_REPLAY_KEY_PREFIX = "captcha:replay:"


class CaptchaAction(StrEnum):
    """Actions passed to reCAPTCHA Enterprise so each endpoint's tokens are
    mutually non-replayable. Enforced via strict equality against
    ``tokenProperties.action`` — a signup token cannot pass the oauth path
    even if siphoned, because the Enterprise response reports the action
    the client embedded at challenge time.
    """

    SIGNUP = "signup"
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
    """Subset of the Enterprise Assessment response we actually read."""

    name: str | None = None
    token_properties: _TokenProperties = Field(
        default_factory=_TokenProperties, alias="tokenProperties"
    )
    risk_analysis: _RiskAnalysis = Field(
        default_factory=_RiskAnalysis, alias="riskAnalysis"
    )


def is_captcha_enabled() -> bool:
    """Captcha is on iff the feature flag is set AND we have an Enterprise
    API key to authenticate with. A missing API key is the kill-switch: the
    module falls through without calling Google so self-hosted and dev
    deployments are unaffected."""
    return CAPTCHA_ENABLED and bool(_RECAPTCHA_ENTERPRISE_API_KEY)


def _replay_cache_key(token: str) -> str:
    """Avoid storing the raw token in Redis — hash it first."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_REPLAY_KEY_PREFIX}{digest}"


async def _reserve_token_or_raise(token: str) -> None:
    """SETNX a token fingerprint. If another caller already claimed it within
    the TTL, reject as a replay. Fails open on Redis errors — losing replay
    protection is strictly better than hard-failing legitimate registrations
    if Redis blips."""
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
    """Unclaim a previously-reserved token so a retry with the same still-valid
    token is not blocked. Called when WE fail (network error talking to
    Google), not when Google rejects the token — Google rejections mean the
    token is permanently invalid and must stay claimed."""
    try:
        redis = await get_async_redis_connection()
        await redis.delete(_replay_cache_key(token))
    except Exception as e:
        logger.error(f"Captcha replay cache release error (ignored): {e}")


def _check_token_freshness(create_time: str | None) -> None:
    """Reject tokens older than the Assessment API's own 2-minute validity
    window. Google enforces this too, but a server-side check is cheap
    defense-in-depth against clock-skew edge cases and reduces reliance
    on a single counterparty.
    """
    if not create_time:
        return
    try:
        # Google returns RFC3339 with `Z`; strip Z and parse as UTC.
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
    """Apply the full rejection ladder to a parsed Assessment response.
    Ordered cheapest-to-most-lenient: fail fast on definitively-bad tokens
    before reaching the grey-area score floor.
    """
    tp = result.token_properties
    ra = result.risk_analysis

    if not tp.valid:
        reason = tp.invalid_reason or "INVALID"
        logger.warning(f"Captcha token invalid: reason={reason}")
        raise CaptchaVerificationError(f"Captcha verification failed: {reason}")

    if tp.hostname and tp.hostname not in _HOSTNAME_ALLOWLIST:
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

    if ra.score < _SCORE_FLOOR:
        logger.warning(
            f"Captcha score below floor: {ra.score} < {_SCORE_FLOOR} reasons={ra.reasons}"
        )
        raise CaptchaVerificationError(
            "Captcha verification failed: suspicious activity detected"
        )

    logger.info(
        f"Captcha verification passed: action={tp.action} score={ra.score} reasons={ra.reasons} hostname={tp.hostname}"
    )


async def verify_captcha_token(token: str, action: CaptchaAction) -> None:
    """Verify a reCAPTCHA token with the Enterprise Assessment API.

    Rejection ladder (strict equality; no silent skip on empty fields):
    tokenProperties.valid → hostname → createTime ≤ 120s → action match →
    riskAnalysis.reasons[] ∩ hard set → score ≥ floor.

    Fails open (returns None) when captcha is disabled. Raises
    ``CaptchaVerificationError`` on any rejection or service outage.
    """
    if not is_captcha_enabled():
        return

    if not token:
        raise CaptchaVerificationError("Captcha token is required")

    # Claim the token first so a concurrent replay of the same value cannot
    # slip through the Google round-trip window. Done BEFORE calling Google
    # because even a still-valid token should only redeem once.
    await _reserve_token_or_raise(token)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                _RECAPTCHA_ASSESSMENT_URL,
                params={"key": _RECAPTCHA_ENTERPRISE_API_KEY},
                json={
                    "event": {
                        "token": token,
                        "siteKey": _RECAPTCHA_SITE_KEY,
                        "expectedAction": action.value,
                    }
                },
                timeout=10.0,
            )
            response.raise_for_status()
            result = RecaptchaAssessmentResponse(**response.json())
            _evaluate_assessment(result, action)

    except CaptchaVerificationError:
        # Definitively-bad token. Keep the replay reservation so the same
        # value cannot be retried elsewhere during the TTL window.
        raise
    except Exception as e:
        # Transport / parse failures are OUR inability to verify, not proof
        # the token is bad. Release the reservation so the user can retry.
        logger.error(f"Captcha verification failed unexpectedly: {e}")
        await _release_token(token)
        raise CaptchaVerificationError("Captcha verification service unavailable")


# ---------------------------------------------------------------------------
# OAuth pre-redirect cookie helpers
# ---------------------------------------------------------------------------


def _cookie_signing_key() -> bytes:
    """Derive a dedicated HMAC key from USER_AUTH_SECRET.

    Using a separate derivation keeps the captcha cookie signature from
    being interchangeable with any other token that reuses USER_AUTH_SECRET.
    """
    return hashlib.sha256(
        f"onyx-captcha-cookie-v1::{USER_AUTH_SECRET}".encode("utf-8")
    ).digest()


def issue_captcha_cookie_value(now: int | None = None) -> str:
    """Produce an opaque cookie value encoding 'verified until <expiry>'.

    Format: ``<expiry_epoch>.<hex_hmac>``. The presence of a valid
    unexpired signature proves the browser solved a captcha challenge
    recently on this origin.
    """
    issued_at = now if now is not None else int(time.time())
    expiry = issued_at + CAPTCHA_COOKIE_TTL_SECONDS
    sig = hmac.new(
        _cookie_signing_key(), str(expiry).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{expiry}.{sig}"


def validate_captcha_cookie_value(value: str | None) -> bool:
    """Return True if the cookie value has a valid unexpired signature.

    The cookie is NOT a JWT — it's a minimal two-field format produced by
    ``issue_captcha_cookie_value``:

        <expiry_epoch_seconds>.<hex_hmac_sha256>

    We split on the first ``.``, parse the expiry as an integer, recompute
    the HMAC over the expiry string using the key derived from
    USER_AUTH_SECRET, and compare with ``hmac.compare_digest`` to avoid
    timing leaks.
    """
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
