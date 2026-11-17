from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from onyx.db.enums import ExternalAppType
from onyx.server.features.build.connect_app import ConnectAppDecision


class ExternalAppUserResponse(BaseModel):
    """User-facing view of an external app.

    `credential_keys` are the parameter names the calling user must supply —
    derived from the app's `auth_template` minus whatever the organization
    has already filled in. `credential_values` are display-safe masked values
    for credentials the user has previously stored for those keys (intersection
    — stale keys from deleted/migrated templates are filtered out).
    `authenticated` is true iff the user has a stored value for every key in
    `credential_keys`.

    Admin-only fields (``organization_credentials``, ``auth_template``,
    ``upstream_url_patterns``, ``enabled``) are intentionally omitted.
    ``app_type`` is included — it's the non-sensitive provider
    discriminator the UI needs to render the app.
    """

    id: int
    # The member sign-in routes under /integrations/{integration_id} take this id.
    integration_id: int
    name: str
    app_type: ExternalAppType
    credential_keys: list[str]
    credential_values: dict[str, Any]
    authenticated: bool
    supports_oauth: bool
    service_urls: list[str] = Field(default_factory=list)


class ConnectAppDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ConnectAppDecision
