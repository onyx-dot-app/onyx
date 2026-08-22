import json
from enum import Enum
from functools import lru_cache
from typing import Any, cast

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import (
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
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


class PublicKeyFormat(Enum):
    JWKS = "jwks"
    PEM = "pem"


# Keyed on the URL so a runtime settings change takes effect without a restart.
@lru_cache(maxsize=8)
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
            response = requests.get(public_key_url)
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
) -> RSAPublicKey | str | None:
    """Return the concrete public key used to verify the provided JWT token."""
    payload = _fetch_public_key_payload(
        public_key_url,
        operator_pinned,
        ssrf_params.allow_private_network,
        ssrf_params.block_loopback_and_link_local,
        ssrf_params.block_link_local_only,
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
    settings = get_security_settings()
    if settings.jwt_public_key_url is None:
        logger.error("JWT public key URL is not configured")
        return None

    # A DB-origin URL is admin-aimed and must satisfy the outbound SSRF policy.
    # An env-pinned value is operator config-as-code, trusted as before.
    operator_pinned = "jwt_public_key_url" in env_pinned_active_fields()
    if not operator_pinned:
        try:
            validate_idp_url(settings.jwt_public_key_url, field="jwt_public_key_url")
        except UnsafeSSOUrl as e:
            logger.error("JWT public key URL rejected: %s", e)
            return None

    for attempt in range(_PUBLIC_KEY_FETCH_ATTEMPTS):
        public_key = get_public_key(
            token,
            settings.jwt_public_key_url,
            operator_pinned,
            outbound_ssrf_params(settings.ssrf_protection_level),
        )
        if public_key is None:
            logger.error("Unable to resolve a public key for JWT verification")
            if attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1:
                _fetch_public_key_payload.cache_clear()
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
            # Definitive claim rejection: refetched keys cannot change it, and a
            # cache clear would let bad tokens evict the signing key for everyone.
            logger.warning("JWT rejected by aud/iss enforcement: %s", str(e))
            return None
        except InvalidTokenError as e:
            logger.error("Invalid JWT token: %s", str(e))
            if attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1:
                _fetch_public_key_payload.cache_clear()
                continue
            return None
        except PyJWTError as e:
            logger.error("JWT decoding error: %s", str(e))
            if attempt < _PUBLIC_KEY_FETCH_ATTEMPTS - 1:
                _fetch_public_key_payload.cache_clear()
                continue
            return None

        return payload

    return None
