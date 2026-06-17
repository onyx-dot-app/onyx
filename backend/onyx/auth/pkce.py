"""Shared PKCE (RFC 7636) primitives.

A single home for the S256 transform so every PKCE call site agrees byte-for-byte
on how a verifier maps to a challenge — the OAuth router's IdP-leg challenge
(`generate_pkce_pair`) and the mobile SSO code store's app-leg verification both
go through `compute_s256_challenge`.
"""

import base64
import hashlib


def compute_s256_challenge(code_verifier: str) -> str:
    """Compute BASE64URL(SHA256(code_verifier)) — the RFC 7636 S256 transform.

    Raises ``ValueError`` (``UnicodeEncodeError``) on a non-ascii verifier; the
    mobile code store relies on this to fail a malformed verifier closed.
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
