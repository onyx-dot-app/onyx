from typing import Any

from pydantic import BaseModel


class PresetGrant(BaseModel):
    # Provider credentials with an absolute ``expires_at`` (ISO string).
    credentials: dict[str, Any]
    # None when the provider gives no signal.
    granted_scopes: list[str] | None
