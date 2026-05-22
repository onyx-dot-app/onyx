"""Proxy-Authorization parsing and session-token validation.

In v0 we hardcode a small allowlist of valid session tokens via the
VALID_SESSION_TOKENS env var (comma-separated). V1 will replace this with a
lookup against the Craft session store.
"""

from __future__ import annotations

import base64
import os

VALID_TOKENS: frozenset[str] = frozenset(
    t for t in (os.getenv("VALID_SESSION_TOKENS", "") or "").split(",") if t
)


def parse_proxy_authorization(
    header_value: str | None,
) -> tuple[str | None, str | None]:
    """Return (user, token) or (None, None) if absent / malformed."""
    if not header_value:
        return (None, None)
    if not header_value.lower().startswith("basic "):
        return (None, None)
    try:
        decoded = base64.b64decode(header_value[6:], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return (None, None)
    if ":" not in decoded:
        return (None, None)
    user, _, token = decoded.partition(":")
    return (user, token)


def is_valid_session_token(token: str | None) -> bool:
    if not token:
        return False
    # Reject control characters early (parser-differential trap).
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in token):
        return False
    return token in VALID_TOKENS
