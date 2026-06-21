from pydantic import BaseModel

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType


class ActionPolicyView(BaseModel):
    """One action of a built-in app, with its effective policy — the admin's
    stored override if set, otherwise the action's ``default_policy``."""

    action_id: str
    normalised_name: str
    description: str
    state: EndpointPolicy


class OrgCredentialFieldDescriptor(BaseModel):
    """One credential field the admin must fill in to configure a
    built-in provider."""

    key: str
    label: str
    description: str
    secret: bool


class EndpointDescriptor(BaseModel):
    """One action in a built-in provider's catalog, flattened for the admin UI.
    The admin picks a policy per action; recognition rules stay backend-side."""

    action_id: str
    normalised_name: str
    description: str
    # The policy a new app's instance of this action defaults to; the create
    # form seeds each action's selector with it (the admin can still override).
    default_policy: EndpointPolicy


class BuiltInExternalAppDescriptor(BaseModel):
    """Backend-defined preset for a built-in OAuth provider. The admin
    UI fetches these and uses them to render the Configure modal +
    POST body, so adding a new provider is a backend-only change."""

    app_type: ExternalAppType
    name: str
    description: str
    upstream_url_patterns: list[str]
    auth_template: dict[str, str]
    required_org_credential_fields: list[OrgCredentialFieldDescriptor]
    setup_instructions: str
    # The catalog of actions an admin can govern (empty for providers without
    # a catalog).
    actions: list[EndpointDescriptor]
