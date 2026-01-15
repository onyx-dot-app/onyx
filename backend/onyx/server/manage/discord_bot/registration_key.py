"""Discord registration key generation and parsing."""

import secrets
from urllib.parse import quote
from urllib.parse import unquote

DISCORD_KEY_PREFIX = "discord_"


def generate_discord_registration_key(tenant_id: str) -> str:
    """Generate a one-time registration key with embedded tenant_id.

    Format: discord_<url_encoded_tenant_id>.<random_token>

    Follows the same pattern as API keys for consistency.
    """
    encoded_tenant = quote(tenant_id)
    random_token = secrets.token_urlsafe(32)
    return f"{DISCORD_KEY_PREFIX}{encoded_tenant}.{random_token}"


def parse_discord_registration_key(key: str) -> tuple[str, str] | None:
    """Parse registration key to extract tenant_id and token.

    Returns (tenant_id, token) or None if invalid format.
    """
    if not key.startswith(DISCORD_KEY_PREFIX):
        return None

    try:
        key_body = key.removeprefix(DISCORD_KEY_PREFIX)
        parts = key_body.split(".", 1)
        if len(parts) != 2:
            return None

        encoded_tenant, token = parts
        tenant_id = unquote(encoded_tenant)
        return tenant_id, token
    except Exception:
        return None
