from typing import Any

from pydantic import BaseModel

# action_type for a domain-matched request that hit no catalog action.
WHOLE_DOMAIN_ACTION_TYPE = "unspecified"


class PresetGrant(BaseModel):
    # Provider credentials with an absolute ``expires_at`` (ISO string).
    credentials: dict[str, Any]
    # None when the provider gives no signal.
    granted_scopes: list[str] | None
