"""Cloudflare Turnstile verification + signed-cookie helpers.

Turnstile is enforced on the signup endpoints as a bot-detection layer. The
frontend renders the Turnstile widget, receives a one-time token, and POSTs
it to ``/api/auth/turnstile/verify``. That endpoint calls Cloudflare's
siteverify API and, on success, issues a signed HttpOnly cookie the client
sends automatically on subsequent signup requests (including the OAuth
callback that we cannot add headers to because it originates from Google).

Downstream middleware on ``/api/auth/register`` and ``/api/auth/oauth/callback``
validates the cookie before the request reaches fastapi-users.

Enforcement is controlled by a single switch: whether TURNSTILE_SECRET_KEY
is set. Deployments that don't want Turnstile (self-hosted, dev, single
tenant) leave it empty and the middleware is a no-op. Cloud sets it and
enforcement activates. One env var, toggleable at runtime, and easy to
exercise end-to-end in local dev.
"""

import hashlib
import hmac
import time
from typing import Any

import httpx

from onyx.configs.app_configs import TURNSTILE_COOKIE_TTL_SECONDS
from onyx.configs.app_configs import TURNSTILE_SECRET_KEY
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.utils.logger import setup_logger

logger = setup_logger()


SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_COOKIE_NAME = "onyx_turnstile_verified"


def turnstile_enforcement_enabled() -> bool:
    """Return True if the signup endpoints should require a valid token."""
    return bool(TURNSTILE_SECRET_KEY)


async def verify_turnstile_token(
    token: str, remote_ip: str | None = None
) -> tuple[bool, str | None]:
    """Call Cloudflare siteverify. Returns (success, error_code_if_any)."""
    if not TURNSTILE_SECRET_KEY:
        # Caller should not invoke when enforcement is off — defensive no-op.
        return True, None

    payload: dict[str, Any] = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(SITEVERIFY_URL, data=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Turnstile siteverify call failed: %s", exc)
        return False, "siteverify-unreachable"

    if body.get("success"):
        return True, None

    error_codes = body.get("error-codes") or []
    logger.info("Turnstile verification rejected: %s", error_codes)
    return False, ",".join(error_codes) if error_codes else "verification-failed"


def _cookie_signing_key() -> bytes:
    """Derive a dedicated HMAC key from USER_AUTH_SECRET.

    Using a separate derivation keeps the turnstile cookie signature from
    being interchangeable with any other token that reuses USER_AUTH_SECRET.
    """
    return hashlib.sha256(
        f"onyx-turnstile-v1::{USER_AUTH_SECRET}".encode("utf-8")
    ).digest()


def issue_turnstile_cookie_value(now: int | None = None) -> str:
    """Produce an opaque cookie value encoding 'verified until <expiry>'.

    Format: ``<expiry_epoch>.<hex_hmac>``. We don't need to carry any other
    claims — the mere presence of a valid unexpired signature proves the
    browser solved a challenge recently on this origin.
    """
    issued_at = now if now is not None else int(time.time())
    expiry = issued_at + TURNSTILE_COOKIE_TTL_SECONDS
    sig = hmac.new(
        _cookie_signing_key(), str(expiry).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{expiry}.{sig}"


def validate_turnstile_cookie_value(value: str | None) -> bool:
    """Return True if the cookie value has a valid unexpired signature."""
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
