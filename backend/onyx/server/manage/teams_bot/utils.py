"""Teams registration key generation and parsing."""

from onyx.onyxbot.registration import generate_registration_key
from onyx.onyxbot.registration import parse_registration_key

REGISTRATION_KEY_PREFIX: str = "teams"


def generate_teams_registration_key(tenant_id: str) -> str:
    """Generate a one-time registration key with embedded tenant_id."""
    return generate_registration_key(REGISTRATION_KEY_PREFIX, tenant_id)


def parse_teams_registration_key(key: str) -> str | None:
    """Parse registration key to extract tenant_id."""
    return parse_registration_key(REGISTRATION_KEY_PREFIX, key)
