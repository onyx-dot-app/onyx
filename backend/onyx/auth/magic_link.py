"""One-time sign-in tokens for the magic link.

The sign-in page takes an email address and the backend mails a link. The link
carries a random token; the shared cache holds the token's hash with what the
click must do: which address to sign in, whether the person chose to start a
new team, and where to land afterwards. Nothing else exists until the link is
clicked, so a made-up address leaves no tenant and no user behind.

Properties enforced here:
  * single-use  -- atomic get-and-delete burns the token on first read
  * short TTL   -- ``MAGIC_LINK_TTL_SECONDS``
  * hashed key  -- the cache holds the token's hash, so a cache dump does not
                   yield working links

Tokens are stored in the cache backend, which every deployment has, so this
works with any ``AUTH_BACKEND``. They are stored in the shared area, not under a
tenant, because the tenant is not known when the link is requested. The redeem
step finds or creates the tenant from the email address in the record.
"""

import asyncio
import hashlib
import secrets

from pydantic import BaseModel, ValidationError

from onyx.cache.factory import get_shared_cache_backend
from onyx.configs.app_configs import MAGIC_LINK_TOKEN_PREFIX, MAGIC_LINK_TTL_SECONDS
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

# The web sends the person to their SSO provider for this error detail.
MAGIC_LINK_USE_SSO_CODE = "MAGIC_LINK_USE_SSO"

# One email per address in this window, whoever asks.
MAGIC_LINK_RESEND_SECONDS = 60
_SEND_KEY_PREFIX = "magic_link_send:"


class MagicLinkRecord(BaseModel):
    """What a click on the link signs in, and where it lands."""

    email: str
    # Playground: the person chose "start a new team" although a team from
    # their domain has a running trial. Rides the token the way the signed
    # OAuth state carries it for Google sign-in.
    start_new_team: bool = False
    next_url: str | None = None
    referral_source: str | None = None


def _cache_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{MAGIC_LINK_TOKEN_PREFIX}{digest}"


def _send_key(email: str) -> str:
    digest = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    return f"{_SEND_KEY_PREFIX}{digest}"


async def reserve_send(email: str) -> bool:
    """Take the one send this address gets per ``MAGIC_LINK_RESEND_SECONDS``.
    False when a link went to it recently."""
    return await asyncio.to_thread(
        get_shared_cache_backend().set_if_absent,
        _send_key(email),
        1,
        MAGIC_LINK_RESEND_SECONDS,
    )


async def release_send(email: str) -> None:
    """Give the send back, for a send that failed."""
    await asyncio.to_thread(get_shared_cache_backend().delete, _send_key(email))


def is_sso_only() -> bool:
    """The admin turned off password sign-in, so everyone signs in through SSO.
    A link sent by email would get around that, so it is off too. Single-tenant
    only, like the password switch."""
    return not MULTI_TENANT and not get_security_settings().password_auth_enabled


async def store_magic_link(record: MagicLinkRecord) -> str:
    """Persist ``record`` under a fresh single-use token and return the token."""
    token = secrets.token_urlsafe(32)
    await asyncio.to_thread(
        get_shared_cache_backend().set,
        _cache_key(token),
        record.model_dump_json(),
        MAGIC_LINK_TTL_SECONDS,
    )
    return token


async def consume_magic_link(token: str) -> MagicLinkRecord | None:
    """Atomically redeem ``token`` and return its record.

    Returns ``None`` when the token is unknown, expired, already used, or its
    record is malformed. One answer for every failure, so the caller shows one
    page and nothing about the address leaks.
    """
    raw = await asyncio.to_thread(get_shared_cache_backend().getdel, _cache_key(token))
    if not raw:
        return None
    try:
        return MagicLinkRecord.model_validate_json(raw)
    except ValidationError as exc:
        # The type only: the record holds the address.
        logger.error("Malformed magic link record (%s); rejecting", type(exc).__name__)
        return None
