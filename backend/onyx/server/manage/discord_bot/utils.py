"""Discord registration key generation and parsing."""

import secrets
from urllib.parse import quote
from urllib.parse import unquote

from onyx.utils.logger import setup_logger

logger = setup_logger()

REGISTRATION_KEY_PREFIX: str = "discord_"


def generate_discord_registration_key(tenant_id: str) -> str:
    """Generate a one-time registration key with embedded tenant_id.

    Format: discord_<url_encoded_tenant_id>.<random_token>

    Follows the same pattern as API keys for consistency.
    """
    encoded_tenant = quote(tenant_id)
    random_token = secrets.token_urlsafe(16)

    logger.info(f"Generated Discord registration key for tenant {tenant_id}")
    return f"{REGISTRATION_KEY_PREFIX}{encoded_tenant}.{random_token}"


def parse_discord_registration_key(key: str) -> str | None:
    """Parse registration key to extract tenant_id.

    Returns tenant_id or None if invalid format.
    """
    if not key.startswith(REGISTRATION_KEY_PREFIX):
        return None

    try:
        key_body = key.removeprefix(REGISTRATION_KEY_PREFIX)
        parts = key_body.split(".", 1)
        if len(parts) != 2:
            return None

        encoded_tenant = parts[0]
        tenant_id = unquote(encoded_tenant)
        return tenant_id
    except Exception:
        return None
