"""Shared registration key generation and parsing for bot integrations."""

import secrets
from urllib.parse import quote
from urllib.parse import unquote

from onyx.utils.logger import setup_logger

logger = setup_logger()


def generate_registration_key(prefix: str, tenant_id: str) -> str:
    """Generate a one-time registration key with embedded tenant_id.

    Format: <prefix>_<url_encoded_tenant_id>.<random_token>
    """
    encoded_tenant = quote(tenant_id)
    random_token = secrets.token_urlsafe(16)

    logger.info(f"Generated {prefix} registration key for tenant {tenant_id}")
    return f"{prefix}_{encoded_tenant}.{random_token}"


def parse_registration_key(prefix: str, key: str) -> str | None:
    """Parse registration key to extract tenant_id.

    Returns tenant_id or None if invalid format.
    """
    full_prefix = f"{prefix}_"
    if not key.startswith(full_prefix):
        return None

    try:
        key_body = key.removeprefix(full_prefix)
        parts = key_body.split(".", 1)
        if len(parts) != 2:
            return None

        encoded_tenant = parts[0]
        return unquote(encoded_tenant)
    except Exception:
        return None
