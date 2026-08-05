"""PKCE (RFC 7636) S256 transform for the mobile SSO bridge.

Used by the mobile SSO code store to verify the app's ``code_verifier``. The web
OAuth flow computes the same transform independently in
``users.generate_pkce_pair``; a test pins that the two agree so they can't drift.
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
