"""Personal Access Token generation and validation."""

import hashlib
import secrets
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from urllib.parse import quote
from urllib.parse import unquote

from fastapi import Request

from onyx.auth.api_key import _API_KEY_HEADER_ALTERNATIVE_NAME
from onyx.auth.api_key import _API_KEY_HEADER_NAME
from onyx.auth.api_key import _BEARER_PREFIX
from shared_configs.configs import MULTI_TENANT


_PAT_PREFIX = "onyx_pat_"
_PAT_LENGTH = 192  # bytes, encoded as base64url


def generate_pat(tenant_id: str | None = None) -> str:
    """Generate cryptographically secure PAT."""
    if MULTI_TENANT and tenant_id:
        encoded_tenant = quote(tenant_id)
        return f"{_PAT_PREFIX}{encoded_tenant}.{secrets.token_urlsafe(_PAT_LENGTH)}"
    return _PAT_PREFIX + secrets.token_urlsafe(_PAT_LENGTH)


def hash_pat(token: str) -> str:
    """Hash PAT using SHA256 (no salt needed due to cryptographic randomness)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_displayable_pat(token: str) -> str:
    """Create masked display version: show prefix + first 4 random chars, mask middle, show last 4.

    Example: onyx_pat_abc1****xyz9
    """
    if len(token) < 12:
        return token
    # Show first 12 chars (onyx_pat_ + 4 random chars) and last 4 chars
    return f"{token[:12]}****{token[-4:]}"


def get_hashed_pat_from_request(request: Request) -> str | None:
    """Extract and hash PAT from Authorization header."""
    auth_header = request.headers.get(
        _API_KEY_HEADER_ALTERNATIVE_NAME
    ) or request.headers.get(_API_KEY_HEADER_NAME)
    if not auth_header or not auth_header.startswith(_BEARER_PREFIX):
        return None

    token = auth_header[len(_BEARER_PREFIX) :].strip()
    if not token.startswith(_PAT_PREFIX):
        return None

    return hash_pat(token)


def calculate_expiration(days: int | None) -> datetime | None:
    """Calculate expiration at 23:59:59.999999 UTC on the target date. None = no expiration."""
    if days is None:
        return None
    expiry_date = datetime.now(timezone.utc).date() + timedelta(days=days)
    return datetime.combine(expiry_date, datetime.max.time()).replace(
        tzinfo=timezone.utc
    )


def extract_tenant_from_pat_header(request: Request) -> str | None:
    """Extract tenant ID from PAT in request. Returns None if not multi-tenant or invalid format."""
    auth_header = request.headers.get(
        _API_KEY_HEADER_ALTERNATIVE_NAME
    ) or request.headers.get(_API_KEY_HEADER_NAME)

    if not auth_header or not auth_header.startswith(_BEARER_PREFIX):
        return None

    token = auth_header[len(_BEARER_PREFIX) :].strip()

    if not token.startswith(_PAT_PREFIX):
        return None

    # Parse tenant from token format: onyx_pat_<tenant>.<random>
    parts = token[len(_PAT_PREFIX) :].split(".", 1)
    if len(parts) != 2:
        return None

    tenant_id = parts[0]
    return unquote(tenant_id) if tenant_id else None
