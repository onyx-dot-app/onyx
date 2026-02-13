"""Captcha verification for user registration."""

import httpx
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import CAPTCHA_ENABLED
from onyx.configs.app_configs import RECAPTCHA_SCORE_THRESHOLD
from onyx.configs.app_configs import RECAPTCHA_SECRET_KEY
from onyx.configs.app_configs import RECAPTCHA_V2_SECRET_KEY
from onyx.configs.constants import AuthType
from onyx.utils.logger import setup_logger

logger = setup_logger()

RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


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

            # For reCAPTCHA v3, also check the score
            if result.score is not None:
                if result.score < RECAPTCHA_SCORE_THRESHOLD:
                    logger.warning(
                        f"Captcha score too low: {result.score} < {RECAPTCHA_SCORE_THRESHOLD}"
                    )
                    raise CaptchaVerificationError(
                        "Captcha verification failed: suspicious activity detected"
                    )

                # Optionally verify the action matches
                if result.action and result.action != expected_action:
                    logger.warning(
                        f"Captcha action mismatch: {result.action} != {expected_action}"
                    )
                    raise CaptchaVerificationError(
                        "Captcha verification failed: action mismatch"
                    )

            logger.debug(
                f"Captcha verification passed: score={result.score}, "
                f"action={result.action}"
            )

    except httpx.HTTPError as e:
        logger.error(f"Captcha API request failed: {e}")
        # In case of API errors, we might want to allow registration
        # to prevent blocking legitimate users. This is a policy decision.
        raise CaptchaVerificationError("Captcha verification service unavailable")


def is_captcha_v2_enabled() -> bool:
    """Check if captcha v2 verification is enabled (cloud only)."""
    return AUTH_TYPE == AuthType.CLOUD and bool(RECAPTCHA_V2_SECRET_KEY)


def verify_captcha_v2_token(token: str) -> None:
    """
    Verify a reCAPTCHA v2 token with Google's API (sync version).

    Args:
        token: The reCAPTCHA response token from the client

    Raises:
        CaptchaVerificationError: If verification fails
    """
    if not RECAPTCHA_V2_SECRET_KEY:
        raise CaptchaVerificationError("reCAPTCHA v2 secret key not configured")

    if not token:
        raise CaptchaVerificationError("Captcha token is required")

    try:
        with httpx.Client() as client:
            response = client.post(
                RECAPTCHA_VERIFY_URL,
                data={
                    "secret": RECAPTCHA_V2_SECRET_KEY,
                    "response": token,
                },
                timeout=10.0,
            )
            response.raise_for_status()

            data = response.json()
            result = RecaptchaResponse(**data)

            if not result.success:
                error_codes = result.error_codes or ["unknown-error"]
                logger.warning(f"Captcha v2 verification failed: {error_codes}")
                raise CaptchaVerificationError(
                    f"Captcha verification failed: {', '.join(error_codes)}"
                )

            logger.debug("Captcha v2 verification passed")

    except httpx.HTTPError as e:
        logger.error(f"Captcha v2 API request failed: {e}")
        raise CaptchaVerificationError("Captcha verification service unavailable")
