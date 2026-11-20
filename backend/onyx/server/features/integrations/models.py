"""Request and response shapes of the integration API."""

from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MCPTransport,
    PluginInstallationPolicy,
)
from onyx.integrations.connection_models import IntegrationStatus
from onyx.integrations.models import EffectivePolicy
from onyx.oauth.models import SafeOAuthReturnPath
from onyx.server.features.mcp.models import HeaderTemplate


class IntegrationShape(str, Enum):
    MCP_SERVER = "mcp_server"
    OPENAPI = "openapi"
    PRESET = "preset"
    CUSTOM = "custom"


class CredentialField(BaseModel):
    key: str
    label: str
    secret: bool


class MemberIntegrationState(str, Enum):
    """What one user gets from an integration. The first that applies, in
    this order."""

    # The user has no access. Only a user who manages the integration gets
    # such a row.
    NO_ACCESS = "no_access"
    # An admin turned the integration off for each user.
    TURNED_OFF = "turned_off"
    # The user has access and the integration is off for the user.
    TURN_ON = "turn_on"
    # On for the user, with no working connection: the user must sign in,
    # or an admin must finish the setup (``status`` gives which).
    SIGN_IN = "sign_in"
    ON = "on"


class IntegrationAccess(BaseModel):
    """The access facts of one integration for the user who reads it."""

    state: MemberIntegrationState
    # The install setting for the user, with the group settings and the
    # owner and share floor. The company setting when the user has no access.
    installation_policy: PluginInstallationPolicy
    # The saved on/off choice of the user. None: the user made no choice.
    user_choice: bool | None
    # The choice under the install setting. A Required integration is on,
    # and a Default one is on until the user turns it off.
    user_enabled: bool
    owner_email: str | None
    is_owner: bool
    # The user can change the integration, its shares and its actions.
    can_manage: bool
    # The company setting is above Not available, so each user has access.
    shared_with_everyone: bool


class IntegrationActionView(BaseModel):
    key: str
    display_name: str
    description: str | None
    read_only: bool | None
    default_policy: EffectivePolicy
    admin_policy: EffectivePolicy | None
    effective_admin_policy: EffectivePolicy
    # Craft asks before each call, whatever the policy is, unless Blocked.
    always_asks: bool


class MemberAction(IntegrationActionView):
    # The user's saved Always allow.
    user_policy: Literal["allow"] | None


class MemberIntegration(BaseModel):
    id: int
    kind: IntegrationKind
    shape: IntegrationShape
    name: str
    description: str | None
    preset_id: str | None
    auth_mode: IntegrationAuthMode
    auth_method: IntegrationAuthMethod | None
    credential_fields: list[CredentialField]
    status: IntegrationStatus
    access: IntegrationAccess
    users_can_save_always_allow: bool
    credential_values: dict[str, str]
    external_app_id: int | None
    service_urls: list[str]
    mcp_server_id: int | None
    server_url: str | None


class MemberIntegrationDetail(MemberIntegration):
    actions: list[MemberAction]


class OAuthClientInput(BaseModel):
    provider_mode: IntegrationOAuthProviderMode
    authorization_url: str | None = None
    token_url: str | None = None
    scopes: list[str] | None = None
    additional_params: dict[str, str] | None = None
    pkce: bool | None = None
    client_id: str | None = None
    # On an update, null keeps the stored secret.
    client_secret: str | None = None


class OAuthClientView(BaseModel):
    provider_mode: IntegrationOAuthProviderMode
    authorization_url: str
    token_url: str
    scopes: list[str] | None
    additional_params: dict[str, str] | None
    pkce: bool | None
    client_id: str | None
    has_client_secret: bool


class McpServerConfigInput(BaseModel):
    shape: Literal[IntegrationShape.MCP_SERVER] = IntegrationShape.MCP_SERVER
    server_url: str
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP


class OpenApiConfigInput(BaseModel):
    shape: Literal[IntegrationShape.OPENAPI] = IntegrationShape.OPENAPI
    openapi_spec: dict[str, Any]


class PresetConfigInput(BaseModel):
    shape: Literal[IntegrationShape.PRESET] = IntegrationShape.PRESET
    preset_id: str
    organization_credentials: dict[str, str] | None = None


class CustomConfigInput(BaseModel):
    shape: Literal[IntegrationShape.CUSTOM] = IntegrationShape.CUSTOM
    upstream_url_patterns: list[str]


IntegrationConfigInput = Annotated[
    McpServerConfigInput | OpenApiConfigInput | PresetConfigInput | CustomConfigInput,
    Field(discriminator="shape"),
]


class PresetConfigView(BaseModel):
    shape: Literal[IntegrationShape.PRESET] = IntegrationShape.PRESET
    preset_id: str


IntegrationConfigView = Annotated[
    McpServerConfigInput | OpenApiConfigInput | PresetConfigView | CustomConfigInput,
    Field(discriminator="shape"),
]


class AdminIntegration(BaseModel):
    id: int
    kind: IntegrationKind
    shape: IntegrationShape
    name: str
    description: str | None
    preset_id: str | None
    enabled: bool
    auth_mode: IntegrationAuthMode
    auth_method: IntegrationAuthMethod | None
    # The company install setting.
    installation_policy: PluginInstallationPolicy
    # What the user who reads the row gets from the integration.
    access: IntegrationAccess
    created_by_email: str | None
    action_count: int
    needs_setup: bool
    setup_reason: str | None
    organization_status: IntegrationStatus | None
    can_manage: bool


class IntegrationGroupShare(BaseModel):
    group_id: int
    group_name: str


class IntegrationGroupSettingView(BaseModel):
    group_id: int
    group_name: str
    installation_policy: PluginInstallationPolicy


class IntegrationGroupSettingChange(BaseModel):
    group_id: int
    # None removes the setting; the group then gets the company setting.
    installation_policy: PluginInstallationPolicy | None


class IntegrationGroupSettingsUpdate(BaseModel):
    """The groups to change. A group left out keeps its setting."""

    group_settings: list[IntegrationGroupSettingChange]


class AdminIntegrationDetail(AdminIntegration):
    config: IntegrationConfigView
    credential_fields: list[CredentialField]
    header_template: dict[str, str] | None
    users_can_save_always_allow: bool
    oauth_client: OAuthClientView | None
    # False when the user cannot manage it, or when Onyx provides the app.
    can_delete: bool
    group_settings: list[IntegrationGroupSettingView]
    # The groups with a share. A shared group cannot be Not available.
    group_shares: list[IntegrationGroupShare]


class PresetView(BaseModel):
    id: str
    name: str
    auth_methods: list[IntegrationAuthMethod | None]
    required_org_credential_fields: list[CredentialField]
    setup_instructions: str | None


class IntegrationCreate(BaseModel):
    for_organization: bool = False
    name: str
    description: str | None = None
    auth_mode: IntegrationAuthMode
    auth_method: IntegrationAuthMethod | None = None
    credential_fields: list[CredentialField] | None = None
    header_template: HeaderTemplate | None = None
    oauth_client: OAuthClientInput | None = None
    config: IntegrationConfigInput


class IntegrationUpdate(BaseModel):
    """Each field that is not sent stays as it is."""

    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    auth_mode: IntegrationAuthMode | None = None
    auth_method: IntegrationAuthMethod | None = None
    credential_fields: list[CredentialField] | None = None
    header_template: HeaderTemplate | None = None
    users_can_save_always_allow: bool | None = None
    oauth_client: OAuthClientInput | None = None
    config: IntegrationConfigInput | None = None


class IntegrationActionsResponse(BaseModel):
    # The admin default row ("Default for new actions"); null = each action
    # uses its own default.
    default_policy: EffectivePolicy | None
    actions: list[IntegrationActionView]


class IntegrationActionsUpdate(BaseModel):
    default_policy: EffectivePolicy | None = None
    actions: dict[str, EffectivePolicy | None] = {}


class ConnectionFieldsRequest(BaseModel):
    fields: dict[str, str]


class ActionGrantsResponse(BaseModel):
    users_can_save_always_allow: bool
    actions: list[MemberAction]


class ActionGrantsUpdate(BaseModel):
    actions: dict[str, Literal["allow"] | None]


class AgentIntegrationOption(BaseModel):
    id: int
    name: str
    description: str | None
    kind: IntegrationKind
    shape: IntegrationShape
    # False: the agent cannot set Allow over an Ask of the admin.
    users_can_save_always_allow: bool
    actions: list[IntegrationActionView]


class IntegrationEnableRequest(BaseModel):
    enabled: bool


class IntegrationInstallationPolicy(BaseModel):
    # The company install setting.
    installation_policy: PluginInstallationPolicy


class IntegrationSharesUpdate(BaseModel):
    """The new set of shares. A share that is not in the lists is removed.
    A share gives use of the integration only."""

    user_ids: list[UUID]
    group_ids: list[int]


class IntegrationUserShare(BaseModel):
    user_id: UUID
    email: str


class IntegrationSharesView(BaseModel):
    integration_id: int
    user_shares: list[IntegrationUserShare]
    group_shares: list[IntegrationGroupShare]


class IntegrationOAuthStartRequest(BaseModel):
    organization: bool = False
    return_path: SafeOAuthReturnPath | None = None


class IntegrationOAuthStartResponse(BaseModel):
    authorization_url: str


class IntegrationOAuthCallbackRequest(BaseModel):
    code: str
    state: str
