from typing import Literal

from pydantic import BaseModel, ConfigDict

from onyx.db.enums import ActionPolicy, ExternalAppType


class ActionPolicyView(BaseModel):
    """One action of a built-in app, with its effective policy — the admin's
    stored override if set, otherwise the action's ``default_policy``."""

    action_id: str
    normalised_name: str
    description: str
    state: ActionPolicy


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
    default_policy: ActionPolicy


class BuiltInExternalAppDescriptor(BaseModel):
    """Backend-defined preset for a built-in OAuth provider. The admin
    UI fetches these and uses them to render the Configure modal +
    POST body, so adding a new provider is a backend-only change."""

    app_type: ExternalAppType
    name: str
    upstream_url_patterns: list[str]
    auth_template: dict[str, str]
    required_org_credential_fields: list[OrgCredentialFieldDescriptor]
    setup_instructions: str
    # The catalog of actions an admin can govern (empty for providers without
    # a catalog).
    actions: list[EndpointDescriptor]


class AppActionPolicies(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gated_app_id: int
    action_policies: dict[str, ActionPolicy]


class TaskAppActionPolicies(AppActionPolicies):
    enabled: bool


class ActionPolicySettingView(BaseModel):
    """One editor row: the current result, workspace rule, and saved owner choice."""

    action_id: str
    normalised_name: str
    description: str
    effective_policy: ActionPolicy
    workspace_policy: ActionPolicy
    stored_policy: ActionPolicy | None
    editable: bool
    lock_reason: Literal["workspace_disabled", "workspace_managed"] | None


class AppActionPoliciesView(BaseModel):
    enabled: bool | None = None
    app_type: ExternalAppType | None = None
    gated_app_id: int
    kind: Literal["external_app", "mcp_server"]
    target_id: int
    name: str
    users_can_manage_policies: bool
    actions: list[ActionPolicySettingView]


class SaveActionPolicies(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_policies: dict[str, ActionPolicy]
