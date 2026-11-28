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
# The address typed to confirm a link opened elsewhere was not the one it went
# to. The link is used up, so the web offers a new one.
MAGIC_LINK_WRONG_EMAIL_CODE = "MAGIC_LINK_WRONG_EMAIL"

# Holds a secret that ties a link to the browser that asked for it. Without
# it, a link forwarded to someone else would sign them in to the sender's
# account. Opened elsewhere, the link asks for the address it was sent to.
MAGIC_LINK_BROWSER_COOKIE = "onyx_magic_link_browser"

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
    # SHA-256 of the secret in the requesting browser's cookie.
    browser_hash: str | None = None
    # The holder already proved the link: a token the redeem route returned to
    # that same page, never mailed. A record with neither needs the address.
    proven: bool = False


def new_browser_secret() -> tuple[str, str]:
    """A secret for the requesting browser's cookie, and its hash for the record."""
    secret = secrets.token_urlsafe(32)
    return secret, _browser_hash(secret)


def _browser_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def opened_where_requested(record: MagicLinkRecord, cookie: str | None) -> bool:
    """True when this browser asked for the link, or already proved it."""
    if record.proven:
        return True
    if not record.browser_hash or not cookie:
        return False
    return secrets.compare_digest(record.browser_hash, _browser_hash(cookie))


def _cache_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{MAGIC_LINK_TOKEN_PREFIX}{digest}"


def _send_key(email: str) -> str:
    digest = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()
    return f"{_SEND_KEY_PREFIX}{digest}"


async def reserve_send(email: str) -> str | None:
    """Take the one send this address gets per ``MAGIC_LINK_RESEND_SECONDS``.

    Returns this request's claim on the slot, for ``release_send``, or None
    when a link went to the address recently.
    """
    claim = secrets.token_hex(16)
    taken = await asyncio.to_thread(
        get_shared_cache_backend().set_if_absent,
        _send_key(email),
        claim,
        MAGIC_LINK_RESEND_SECONDS,
    )
    return claim if taken else None


async def release_send(email: str, claim: str) -> None:
    """Give the slot back after a failed send. Only while it still holds this
    request's claim: once it has expired, a newer request may hold it."""
    await asyncio.to_thread(
        get_shared_cache_backend().delete_if_value,
        _send_key(email),
        claim.encode("utf-8"),
    )


def is_sso_only(*, allow_fallback: bool = False) -> bool:
    """The admin turned off password sign-in, so everyone signs in through SSO.
    A link sent by email would get around that, so it is off too. Single-tenant
    only, like the password switch.

    Raises when the settings cannot be read: the fallback defaults allow
    passwords, which would let a link past SSO. ``allow_fallback=True`` is for
    display hints only.
    """
    if MULTI_TENANT:
        return False
    settings = get_security_settings(allow_fallback=allow_fallback)
    return not settings.password_auth_enabled


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


async def peek_magic_link(token: str) -> MagicLinkRecord | None:
    """Read ``token``'s record without using the token up, so the redeem route
    can ask for the address first. ``None`` as for ``consume_magic_link``."""
    raw = await asyncio.to_thread(get_shared_cache_backend().get, _cache_key(token))
    return _parse_record(raw)


async def consume_magic_link(token: str) -> MagicLinkRecord | None:
    """Atomically redeem ``token`` and return its record.

    Returns ``None`` when the token is unknown, expired, already used, or its
    record is malformed. One answer for every failure, so the caller shows one
    page and nothing about the address leaks.
    """
    raw = await asyncio.to_thread(get_shared_cache_backend().getdel, _cache_key(token))
    return _parse_record(raw)


def _parse_record(raw: bytes | None) -> MagicLinkRecord | None:
    if not raw:
        return None
    try:
        return MagicLinkRecord.model_validate_json(raw)
    except ValidationError as exc:
        # The type only: the record holds the address.
        logger.error("Malformed magic link record (%s); rejecting", type(exc).__name__)
        return None
