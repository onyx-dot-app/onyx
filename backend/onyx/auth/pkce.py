"""PKCE (RFC 7636) S256 helpers for OAuth flows."""

import base64
import hashlib
import secrets


def compute_s256_challenge(code_verifier: str) -> str:
    """Compute BASE64URL(SHA256(code_verifier)) — the RFC 7636 S256 transform.

    Raises ``ValueError`` (``UnicodeEncodeError``) on a non-ascii verifier; the
    mobile code store relies on this to fail a malformed verifier closed.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    return code_verifier, compute_s256_challenge(code_verifier)
