"""Captcha verification for user registration."""

import httpx
from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import CAPTCHA_ENABLED
from onyx.configs.app_configs import RECAPTCHA_SCORE_THRESHOLD
from onyx.configs.app_configs import RECAPTCHA_SECRET_KEY
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

    except httpx.HTTPError as e:
        logger.error(f"Captcha API request failed: {e}")
        # In case of API errors, we might want to allow registration
        # to prevent blocking legitimate users. This is a policy decision.
        raise CaptchaVerificationError("Captcha verification service unavailable")
