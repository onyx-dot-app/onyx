"""Personal Access Token generation and validation."""

import hashlib
import secrets
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from urllib.parse import quote

from fastapi import Request

from onyx.auth.constants import PAT_LENGTH
from onyx.auth.constants import PAT_PREFIX
from onyx.auth.utils import get_hashed_bearer_token_from_request
from shared_configs.configs import MULTI_TENANT


def generate_pat(tenant_id: str | None = None) -> str:
    """Generate cryptographically secure PAT."""
    if MULTI_TENANT and tenant_id:
        encoded_tenant = quote(tenant_id)
        return f"{PAT_PREFIX}{encoded_tenant}.{secrets.token_urlsafe(PAT_LENGTH)}"
    return PAT_PREFIX + secrets.token_urlsafe(PAT_LENGTH)


def hash_pat(token: str) -> str:
    """Hash PAT using SHA256 (no salt needed due to cryptographic randomness)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_displayable_pat(token: str) -> str:
    """Create masked display version: show prefix + first 4 random chars, mask middle, show last 4.

    Example: onyx_pat_abc1****xyz9
    """
    # Show first 12 chars (onyx_pat_ + 4 random chars) and last 4 chars
    return f"{token[:12]}****{token[-4:]}"


def get_hashed_pat_from_request(request: Request) -> str | None:
    """Extract and hash PAT from Authorization header.

    Only accepts "Bearer <token>" format (unlike API keys which support raw format).
    """
    return get_hashed_bearer_token_from_request(
        request,
        valid_prefixes=[PAT_PREFIX],
        hash_fn=hash_pat,
        allow_non_bearer=False,  # PATs require Bearer prefix
    )


def calculate_expiration(days: int | None) -> datetime | None:
    """Calculate expiration at 23:59:59.999999 UTC on the target date. None = no expiration."""
    if days is None:
        return None
    expiry_date = datetime.now(timezone.utc).date() + timedelta(days=days)
    return datetime.combine(expiry_date, datetime.max.time()).replace(
        tzinfo=timezone.utc
    )
