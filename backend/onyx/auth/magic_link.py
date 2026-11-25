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
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
