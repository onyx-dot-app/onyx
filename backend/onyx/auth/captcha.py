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
"""

import hashlib
import hmac
import time

import httpx
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import CAPTCHA_COOKIE_TTL_SECONDS
from onyx.configs.app_configs import CAPTCHA_ENABLED
from onyx.configs.app_configs import RECAPTCHA_SCORE_THRESHOLD
from onyx.configs.app_configs import RECAPTCHA_SECRET_KEY
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger

logger = setup_logger()

RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
CAPTCHA_COOKIE_NAME = "onyx_captcha_verified"

# Google v3 tokens expire server-side at ~2 minutes, so 120s is the max useful
# replay window — after that Google would reject the token anyway.
_REPLAY_CACHE_TTL_SECONDS = 120
_REPLAY_KEY_PREFIX = "captcha:replay:"


class CaptchaVerificationError(Exception):
    """Raised when captcha verification fails."""


class RecaptchaResponse(BaseModel):
    """Response from Google reCAPTCHA verification API."""

    success: bool
    score: float | None = None  # Only present for reCAPTCHA v3
    action: str | None = None
    challenge_ts: str | None = None
    hostname: str | None = None
    error_codes: list[str] | None = Field(default=None, alias="error-codes")


def is_captcha_enabled() -> bool:
    """Check if captcha verification is enabled."""
    return CAPTCHA_ENABLED and bool(RECAPTCHA_SECRET_KEY)


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
        # Worst case: the user must wait up to 120s before the TTL expires
        # on its own and they can retry. Still strictly better than failing
        # open on the reservation side.
        logger.error(f"Captcha replay cache release error (ignored): {e}")


async def verify_captcha_token(
    token: str,
    expected_action: str = "signup",
) -> None:
    """
    Verify a reCAPTCHA token with Google's API.

    Args:
        token: The reCAPTCHA response token from the client
        expected_action: Expected action name for v3 verification

    Raises:
        CaptchaVerificationError: If verification fails
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
                RECAPTCHA_VERIFY_URL,
                data={
                    "secret": RECAPTCHA_SECRET_KEY,
                    "response": token,
                },
                timeout=10.0,
            )
            response.raise_for_status()

            data = response.json()
            result = RecaptchaResponse(**data)

            if not result.success:
                error_codes = result.error_codes or ["unknown-error"]
                logger.warning(f"Captcha verification failed: {error_codes}")
                raise CaptchaVerificationError(
                    f"Captcha verification failed: {', '.join(error_codes)}"
                )

            # Require v3 score. Google's public test secret returns no score
            # — that path must not be active in prod since it skips the only
            # human-vs-bot signal. A missing score here means captcha is
            # misconfigured (test secret in prod, or a v2 response slipped in
            # via an action mismatch).
            if result.score is None:
                logger.warning(
                    "Captcha verification failed: siteverify returned no score (likely test secret in prod)"
                )
                raise CaptchaVerificationError(
                    "Captcha verification failed: missing score"
                )

            if result.score < RECAPTCHA_SCORE_THRESHOLD:
                logger.warning(
                    f"Captcha score too low: {result.score} < {RECAPTCHA_SCORE_THRESHOLD}"
                )
                raise CaptchaVerificationError(
                    "Captcha verification failed: suspicious activity detected"
                )

            if result.action and result.action != expected_action:
                logger.warning(
                    f"Captcha action mismatch: {result.action} != {expected_action}"
                )
                raise CaptchaVerificationError(
                    "Captcha verification failed: action mismatch"
                )

            logger.debug(
                f"Captcha verification passed: score={result.score}, action={result.action}"
            )

    except CaptchaVerificationError:
        # Definitively-bad token (Google rejected it, score too low, action
        # mismatch). Keep the reservation so the same token cannot be
        # retried elsewhere during the TTL window.
        raise
    except Exception as e:
        # Anything else — network failure, JSON decode error, Pydantic
        # validation error on an unexpected siteverify response shape — is
        # OUR inability to verify the token, not proof the token is bad.
        # Release the reservation so the user can retry with the same
        # still-valid token instead of being locked out for ~120s.
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
    timing leaks. No base64, no JSON, no claims — anything fancier would
    be overkill for a short-lived "verified recently" cookie.
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
