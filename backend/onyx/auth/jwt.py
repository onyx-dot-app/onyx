import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import (
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    MissingRequiredClaimError,
    PyJWTError,
)
from jwt import decode as jwt_decode
from jwt.algorithms import RSAAlgorithm  # ty: ignore[possibly-missing-import]

from onyx.auth.sso_url_guard import UnsafeSSOUrl, validate_idp_url
from onyx.server.security.models import OutboundSSRFParams, outbound_ssrf_params
from onyx.server.security.store import (
    env_pinned_active_fields,
    get_security_settings,
)
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, ssrf_safe_get

logger = setup_logger()


_PUBLIC_KEY_FETCH_ATTEMPTS = 2
_PUBLIC_KEY_FETCH_TIMEOUT_SECONDS = 15
# Caller-supplied tokens can force a refetch, so bound how often that happens.
_PUBLIC_KEY_REFRESH_MIN_INTERVAL_SECONDS = 60.0
# Shorter wait after a failed fetch, so an IdP outage ends soon after recovery.
_PUBLIC_KEY_FETCH_FAILURE_BACKOFF_SECONDS = 5.0
_MAX_CACHED_PUBLIC_KEY_URLS = 8


class PublicKeyFormat(Enum):
    JWKS = "jwks"
    PEM = "pem"


_KeyPayload = tuple[str | dict[str, Any], PublicKeyFormat]
# (url, operator_pinned, allow_private_network, block_loopback_and_link_local,
# block_link_local_only). Keyed on the URL so a runtime settings change takes
# effect without a restart.
_KeyCacheKey = tuple[str, bool, bool, bool, bool]


@dataclass
class _KeyCacheEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    fetched: bool = False
    payload: _KeyPayload | None = None
    next_fetch_allowed: float = float("-inf")


_key_cache: dict[_KeyCacheKey, _KeyCacheEntry] = {}
_key_cache_lock = threading.Lock()


def _reset_public_key_cache() -> None:
    with _key_cache_lock:
        _key_cache.clear()


def _get_public_key_payload(
    cache_key: _KeyCacheKey, force_refresh: bool
) -> _KeyPayload | None:
    """Return cached key material. Refetches are rate-limited per URL: a long
    interval after a successful refresh, a short backoff after a failed fetch.
    Concurrent callers share one fetch."""
    with _key_cache_lock:
        entry = _key_cache.get(cache_key)
        if entry is None:
            if len(_key_cache) >= _MAX_CACHED_PUBLIC_KEY_URLS:
                _key_cache.pop(next(iter(_key_cache)))
            entry = _key_cache[cache_key] = _KeyCacheEntry()

    with entry.lock:
        if entry.fetched:
            if entry.payload is not None and not force_refresh:
                return entry.payload
            if time.monotonic() < entry.next_fetch_allowed:
                return entry.payload
        was_fetched = entry.fetched
        payload = _fetch_public_key_payload(*cache_key)
        entry.fetched = True
        now = time.monotonic()
        if payload is None:
            # Keep any earlier good keys; a failed refresh must not evict them.
            entry.next_fetch_allowed = now + _PUBLIC_KEY_FETCH_FAILURE_BACKOFF_SECONDS
        else:
            entry.payload = payload
            if was_fetched:
                entry.next_fetch_allowed = (
                    now + _PUBLIC_KEY_REFRESH_MIN_INTERVAL_SECONDS
                )
        return entry.payload


def _fetch_public_key_payload(
    public_key_url: str,
    operator_pinned: bool,
    allow_private_network: bool,
    block_loopback_and_link_local: bool,
    block_link_local_only: bool,
) -> tuple[str | dict[str, Any], PublicKeyFormat] | None:
    """Fetch and cache the raw JWT verification material. A DB-origin URL is
    admin-aimed, so its fetch validates every redirect hop and pins the
    resolved IP against DNS rebinding. An env-pinned URL is operator
    config-as-code and fetched as-is."""
    try:
        if operator_pinned:
            response = requests.get(
                public_key_url, timeout=_PUBLIC_KEY_FETCH_TIMEOUT_SECONDS
            )
        else:
            # Mirrors the PUT-time check: the configured SSRF level decides
            # whether private endpoints are reachable.
            # https_only holds across redirect hops, so no hop can downgrade
            # the key fetch to plaintext.
            response = ssrf_safe_get(
                public_key_url,
                allow_private_network=allow_private_network,
                block_loopback_and_link_local=block_loopback_and_link_local,
                block_link_local_only=block_link_local_only,
                https_only=True,
            )
        response.raise_for_status()
    except (requests.RequestException, SSRFException, ValueError) as exc:
        logger.error("Failed to fetch JWT public key: %s", str(exc))
        return None
    content_type = response.headers.get("Content-Type", "").lower()
    raw_body = response.text
    body_lstripped = raw_body.lstrip()

    if "application/json" in content_type or body_lstripped.startswith("{"):
        try:
            data = response.json()
        except ValueError:
            logger.error("JWT public key URL returned invalid JSON")
            return None

        if isinstance(data, dict) and "keys" in data:
            return data, PublicKeyFormat.JWKS

        logger.error(
            "JWT public key URL returned JSON but no JWKS 'keys' field was found"
        )
        return None

    body = raw_body.strip()
    if not body:
        logger.error("JWT public key URL returned an empty response")
        return None

    return body, PublicKeyFormat.PEM


def get_public_key(
    token: str,
    public_key_url: str,
    operator_pinned: bool,
    ssrf_params: OutboundSSRFParams,
    force_refresh: bool = False,
) -> RSAPublicKey | str | None:
    """Return the concrete public key used to verify the provided JWT token."""
    payload = _get_public_key_payload(
        (
            public_key_url,
            operator_pinned,
            ssrf_params.allow_private_network,
            ssrf_params.block_loopback_and_link_local,
            ssrf_params.block_link_local_only,
        ),
        force_refresh,
    )
    if payload is None:
        logger.error("Failed to retrieve public key payload")
        return None

    key_material, key_format = payload

    if key_format is PublicKeyFormat.JWKS:
        jwks_data = cast(dict[str, Any], key_material)
        return _resolve_public_key_from_jwks(token, jwks_data)

    return cast(str, key_material)


def _resolve_public_key_from_jwks(
    token: str, jwks_payload: dict[str, Any]
) -> RSAPublicKey | None:
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as e:
        logger.error("Unable to parse JWT header: %s", str(e))
        return None

    keys = jwks_payload.get("keys", []) if isinstance(jwks_payload, dict) else []
    if not keys:
        logger.error("JWKS payload did not contain any keys")
        return None

    kid = header.get("kid")
    thumbprint = header.get("x5t")

    candidates = []
    if kid:
        candidates = [k for k in keys if k.get("kid") == kid]
    if not candidates and thumbprint:
        candidates = [k for k in keys if k.get("x5t") == thumbprint]
    if not candidates and len(keys) == 1:
        candidates = keys

    if not candidates:
        logger.warning(
            "No matching JWK found for token header (kid=%s, x5t=%s)", kid, thumbprint
        )
        return None

    if len(candidates) > 1:
        logger.warning(
            "Multiple JWKs matched token header kid=%s; selecting the first occurrence",
            kid,
        )

    jwk = candidates[0]
    try:
        return cast(RSAPublicKey, RSAAlgorithm.from_jwk(json.dumps(jwk)))
    except ValueError as e:
        logger.error("Failed to construct RSA key from JWK: %s", str(e))
        return None


async def verify_jwt_token(token: str) -> dict[str, Any] | None:
    # Non-JWT bearers (PATs, API keys) must not reach the DNS check or key fetch.
    if token.count(".") != 2:
        return None
    try:
        jwt.get_unverified_header(token)
    except PyJWTError:
        return None

    settings = get_security_settings()
    if settings.jwt_public_key_url is None:
        logger.error("JWT public key URL is not configured")
        return None

    # A DB-origin URL is admin-aimed and must satisfy the outbound SSRF policy.
    # An env-pinned value is operator config-as-code, trusted as before.
    operator_pinned = "jwt_public_key_url" in env_pinned_active_fields()
    if not operator_pinned:
        try:
            # Resolves DNS, so it runs off the event loop.
            await asyncio.to_thread(
                validate_idp_url,
                settings.jwt_public_key_url,
                field="jwt_public_key_url",
            )
        except UnsafeSSOUrl as e:
            logger.error("JWT public key URL rejected: %s", e)
            return None

    ssrf_params = outbound_ssrf_params(settings.ssrf_protection_level)
    for attempt in range(_PUBLIC_KEY_FETCH_ATTEMPTS):
        # A retry means the signing key may have rotated. The fetch is
        # blocking I/O, so it runs off the event loop.
        can_retry = attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1
        public_key = await asyncio.to_thread(
            get_public_key,
            token,
            settings.jwt_public_key_url,
            operator_pinned,
            ssrf_params,
            attempt > 0,
        )
        if public_key is None:
            logger.error("Unable to resolve a public key for JWT verification")
            if can_retry:
                continue
            return None

        try:
            # Enforced only when configured: verify_aud=True with audience=None
            # would reject every token that carries an aud claim.
            payload = jwt_decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=settings.jwt_expected_audience,
                issuer=settings.jwt_expected_issuer,
                options={"verify_aud": settings.jwt_expected_audience is not None},
            )
        except (
            InvalidAudienceError,
            InvalidIssuerError,
            MissingRequiredClaimError,
        ) as e:
            logger.warning("JWT rejected by aud/iss enforcement: %s", str(e))
            return None
        except InvalidSignatureError as e:
            logger.error("Invalid JWT signature: %s", str(e))
            if can_retry:
                continue
            return None
        except PyJWTError as e:
            # Expired or malformed tokens: new keys cannot change the result.
            logger.error("Invalid JWT token: %s", str(e))
            return None

        return payload

    return None
