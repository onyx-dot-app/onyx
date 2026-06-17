"""One-time, PKCE-bound SSO code store (Redis).

The mobile SSO bridge never puts a session token on the (interceptable)
custom-scheme deep link. Instead the backend stores the freshly minted token in
Redis under a short-lived, single-use code bound to an app-supplied PKCE
challenge, and hands the deep link only that opaque code. The app later swaps the
code for the token over TLS, proving possession of the matching ``code_verifier``
— so a hijacked code is useless to an attacker who never saw the verifier.

Security properties enforced here:
  * single-use  -- atomic ``GETDEL`` burns the code on first read
  * short TTL   -- ``MOBILE_SSO_CODE_TTL_SECONDS`` (default 60s)
  * PKCE (S256) -- the verifier is hashed and constant-time-compared to the
                   stored challenge (RFC 7636)

Redis is core infra (always available, even when ``AUTH_BACKEND=jwt``), so this
store works across every auth backend. Keys are a single global namespace: a
code is a high-entropy random value mapping to exactly one already-tenant-bound
token, so there is no cross-tenant ambiguity.
"""

import json
import secrets

from onyx.auth.pkce import compute_s256_challenge
from onyx.configs.app_configs import MOBILE_SSO_CODE_PREFIX
from onyx.configs.app_configs import MOBILE_SSO_CODE_TTL_SECONDS
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.utils.logger import setup_logger

logger = setup_logger()


async def store_sso_code(token: str, code_challenge: str) -> str:
    """Persist ``token`` under a fresh single-use code bound to ``code_challenge``.

    Returns the opaque code to place on the deep link. The token itself already
    encodes tenant context, so nothing tenant-specific is stored alongside it.
    """
    code = secrets.token_urlsafe(32)
    record = {"token": token, "code_challenge": code_challenge}
    redis = await get_async_redis_connection()
    await redis.set(
        f"{MOBILE_SSO_CODE_PREFIX}{code}",
        json.dumps(record),
        ex=MOBILE_SSO_CODE_TTL_SECONDS,
    )
    return code


async def consume_sso_code(code: str, code_verifier: str) -> str | None:
    """Atomically redeem ``code`` and return the token, or ``None`` on any failure.

    Returns ``None`` — never raises, never distinguishes the reason — when the
    code is missing, expired, already used, the verifier is malformed, or the
    PKCE verifier doesn't match, so the caller can surface one generic error with
    no oracle. The code is burned (``GETDEL``) before the PKCE check, so a wrong
    verifier cannot be retried against the same code.
    """
    redis = await get_async_redis_connection()
    # Atomic get-and-delete enforces single use (Redis 6.2+).
    raw = await redis.getdel(f"{MOBILE_SSO_CODE_PREFIX}{code}")
    if not raw:
        return None

    try:
        record = json.loads(raw)
        stored_challenge = record["code_challenge"]
        token = record["token"]
        # A non-str challenge would make compare_digest raise TypeError below;
        # treat a malformed record as the same generic miss to keep the
        # fail-closed contract.
        if not isinstance(stored_challenge, str) or not isinstance(token, str):
            raise TypeError("malformed code record")
        # A malformed verifier (e.g. non-ascii) must fail closed as the same
        # generic miss — compute_s256_challenge raises ValueError on bad input.
        provided_challenge = compute_s256_challenge(code_verifier)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        # Log the exception *type* only (never the value — that could leak the
        # verifier) so a malformed record is distinguishable in logs from a
        # normal miss.
        logger.error(
            "Malformed mobile SSO code record or verifier (%s); rejecting",
            type(exc).__name__,
        )
        return None

    if not secrets.compare_digest(provided_challenge, stored_challenge):
        return None

    return token
