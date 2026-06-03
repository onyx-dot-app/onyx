"""RSA key pair management for LTI 1.3 JWKS endpoint.

Generates a persistent RSA key pair on first use and caches it in Redis
so all backend instances share the same key. If no Redis entry exists,
a new 2048-bit RSA key is generated and stored.

The public key is served at /auth/lti/jwks in JWK Set format. The
private key is available for signing service requests back to Canvas
(LTI Advantage), though that is not yet implemented.
"""

import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from onyx.utils.logger import setup_logger


logger = setup_logger()

_REDIS_KEY = "lti_jwks_private_key_pem"
_KID = "onyx-lti-1"

# Module-level cache so we don't regenerate on every request
_cached_private_key: rsa.RSAPrivateKey | None = None
_cached_jwks: dict | None = None


def _generate_rsa_key_pair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _private_key_to_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _pem_to_private_key(pem: bytes) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("Expected RSA private key")
    return key


def _int_to_base64url(n: int) -> str:
    """Convert a positive integer to a Base64url-encoded string (no padding)."""
    import base64

    byte_length = (n.bit_length() + 7) // 8
    raw = n.to_bytes(byte_length, byteorder="big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _build_jwks(key: rsa.RSAPrivateKey) -> dict:
    """Build a JWK Set dict from the RSA private key's public component."""
    pub = key.public_key().public_numbers()

    # Derive a stable kid from the public key modulus
    mod_bytes = pub.n.to_bytes((pub.n.bit_length() + 7) // 8, byteorder="big")
    kid = hashlib.sha256(mod_bytes).hexdigest()[:16]

    return {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": kid,
                "n": _int_to_base64url(pub.n),
                "e": _int_to_base64url(pub.e),
            }
        ]
    }


def _ensure_key() -> rsa.RSAPrivateKey:
    """Return the cached private key, loading from Redis or generating if needed."""
    global _cached_private_key, _cached_jwks

    if _cached_private_key is not None:
        return _cached_private_key

    # Try loading from Redis (synchronous -- this runs at import/startup time)
    try:
        from onyx.redis.redis_pool import get_shared_redis_client

        redis_client = get_shared_redis_client()
        pem_data = redis_client.get(_REDIS_KEY)
        if pem_data:
            _cached_private_key = _pem_to_private_key(
                pem_data if isinstance(pem_data, bytes) else pem_data.encode()
            )
            _cached_jwks = _build_jwks(_cached_private_key)
            logger.info("Loaded LTI JWKS key from Redis")
            return _cached_private_key
    except Exception:
        logger.debug("Could not load LTI key from Redis, will generate new one")

    # Generate a new key pair
    _cached_private_key = _generate_rsa_key_pair()
    _cached_jwks = _build_jwks(_cached_private_key)
    logger.info("Generated new LTI JWKS key pair")

    # Try to persist to Redis so other instances share the same key
    try:
        pem = _private_key_to_pem(_cached_private_key)
        redis_client = get_shared_redis_client()
        redis_client.set(_REDIS_KEY, pem)
        logger.info("Persisted LTI JWKS key to Redis")
    except Exception:
        logger.warning("Could not persist LTI JWKS key to Redis")

    return _cached_private_key


def get_public_jwks() -> dict:
    """Return the JWK Set containing Onyx's public key."""
    global _cached_jwks
    _ensure_key()
    assert _cached_jwks is not None
    return _cached_jwks


def get_private_key() -> rsa.RSAPrivateKey:
    """Return the private key (for signing LTI Advantage requests)."""
    return _ensure_key()


def get_signing_kid() -> str:
    """Return the `kid` of the public key served at /auth/lti/jwks.

    LTI Advantage service calls (e.g. NRPS) sign a client-assertion JWT that the
    platform verifies against this JWKS, so the assertion's `kid` header must
    match the key id we publish.
    """
    jwks = get_public_jwks()
    return str(jwks["keys"][0]["kid"])
