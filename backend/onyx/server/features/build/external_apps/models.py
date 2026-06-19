from typing import Any

from pydantic import BaseModel

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.models import ActionPolicyView


class CreateBuiltInExternalAppRequest(BaseModel):
    """Create a built-in external app (``POST /admin/apps/built-in``).

    Built-in providers only — ``app_type=CUSTOM`` is rejected (custom apps use
    ``POST /admin/apps/custom``). Updates go through ``PATCH /admin/apps/{id}``.

    A new row is inserted (and a backing ``Skill`` row is created in the same
    transaction). ``upstream_url_patterns`` is a list of regex patterns matched
    by the egress proxy against outbound request URLs. ``enabled`` (stored on
    the linked skill) is the kill switch the proxy checks before injecting
    credentials.

    Skill identity (slug, bundle bytes, sharing scope) is derived server-side
    from ``app_type``; admins don't supply it.
    """

    name: str
    description: str
    enabled: bool
    app_type: ExternalAppType
    upstream_url_patterns: list[str]
    auth_template: dict[str, Any]
    organization_credentials: dict[str, str]
    # Map full-replaces stored overrides (empty clears); None defaults every
    # action. Keyed by catalog action id; validated on create.
    action_policies: dict[str, EndpointPolicy] | None = None


class UpdateExternalAppRequest(BaseModel):
    """Partial update of an existing app, keyed solely by the path ``id``
    (``PATCH /admin/apps/{id}``). Every field is optional; ``None`` means "leave
    untouched", so a narrow request (e.g. just ``enabled``) won't blank the rest.

    This is the single update path for built-in apps. For Onyx-managed built-ins
    (cloud) the gateway-config fields (``upstream_url_patterns``,
    ``auth_template``, ``organization_credentials``) are Onyx-owned and ignored —
    only ``enabled`` + ``action_policies`` take effect. Custom-app field edits
    (and bundle replacement) go through ``POST /admin/apps/custom`` instead, since
    that path is multipart.
    """

    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    upstream_url_patterns: list[str] | None = None
    auth_template: dict[str, Any] | None = None
    organization_credentials: dict[str, str] | None = None
    # Full-replace stored overrides when present (empty clears); None leaves them.
    action_policies: dict[str, EndpointPolicy] | None = None


class ExternalAppAdminResponse(BaseModel):
    """Admin-facing view of an external app (includes org credentials)."""

    id: int
    name: str
    description: str
    app_type: ExternalAppType
    upstream_url_patterns: list[str]
    auth_template: dict[str, Any]
    organization_credentials: dict[str, Any]
    enabled: bool
    # The merged per-action policy view (built-in apps; empty for custom).
    actions: list[ActionPolicyView]
    # Onyx-managed built-in (cloud): creds/config Onyx-owned and blanked above;
    # admin may only enable/disable + set policies. UI hides the rest.
    is_onyx_managed: bool = False


class UpsertUserCredentialsRequest(BaseModel):
    """User-supplied credentials for a specific external app."""

    user_credentials: dict[str, Any]


class ExternalAppUserResponse(BaseModel):
    """User-facing view of an external app.

    `credential_keys` are the parameter names the calling user must supply —
    derived from the app's `auth_template` minus whatever the organization
    has already filled in. `credential_values` are the values the user has
    previously stored for those keys (intersection — stale keys from
    deleted/migrated templates are filtered out). `authenticated` is true
    iff `credential_values` covers every key in `credential_keys`.

    Admin-only fields (``organization_credentials``, ``auth_template``,
    ``upstream_url_patterns``, ``enabled``) are intentionally omitted.
    ``app_type`` is included — it's the non-sensitive provider
    discriminator the UI needs to render the app.
    """

    id: int
    name: str
    description: str
    slug: str
    app_type: ExternalAppType
    credential_keys: list[str]
    credential_values: dict[str, Any]
    authenticated: bool


class OAuthStartResponse(BaseModel):
    authorize_url: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class OAuthCallbackResponse(BaseModel):
    success: bool
    external_app_id: int
