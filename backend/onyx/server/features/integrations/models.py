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
    SkillSharePermission,
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


class IntegrationPluginRef(BaseModel):
    plugin_id: UUID
    plugin_name: str
    scope: Literal["organization", "personal"]
    owner_email: str | None
    installation_policy: PluginInstallationPolicy | None


class MemberPluginRef(IntegrationPluginRef):
    # The user's own on/off choice for the plugin.
    enabled: bool


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
    plugins: list[MemberPluginRef]
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
    plugins: list[IntegrationPluginRef]
    created_by_email: str | None
    action_count: int
    needs_setup: bool
    setup_reason: str | None
    organization_status: IntegrationStatus | None
    can_manage: bool


class AdminIntegrationDetail(AdminIntegration):
    config: IntegrationConfigView
    credential_fields: list[CredentialField]
    header_template: dict[str, str] | None
    users_can_save_always_allow: bool
    oauth_client: OAuthClientView | None
    # False when the user cannot manage it, or when Onyx provides the app.
    can_delete: bool


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
    kind: IntegrationKind
    shape: IntegrationShape
    # False: the agent cannot set Allow over an Ask of the admin.
    users_can_save_always_allow: bool
    actions: list[IntegrationActionView]


class AgentPluginOption(BaseModel):
    plugin_id: UUID
    plugin_name: str
    description: str
    integrations: list[AgentIntegrationOption]


class PluginEnableRequest(BaseModel):
    enabled: bool


class MemberPluginState(BaseModel):
    plugin_id: UUID
    enabled: bool
    # The install setting for the user, with the group settings and the
    # owner and share floor.
    installation_policy: PluginInstallationPolicy


class PluginInstallationPolicyUpdate(BaseModel):
    installation_policy: PluginInstallationPolicy


class PluginUserShare(BaseModel):
    user_id: UUID
    permission: SkillSharePermission


class PluginGroupShare(BaseModel):
    group_id: int
    permission: SkillSharePermission


class PluginAccessUpdate(BaseModel):
    """The new set of shares. A share that is not in the lists is removed."""

    user_shares: list[PluginUserShare]
    group_shares: list[PluginGroupShare]


class PluginUserShareView(PluginUserShare):
    email: str


class PluginGroupShareView(PluginGroupShare):
    group_name: str


class PluginAccessView(BaseModel):
    plugin_id: UUID
    user_shares: list[PluginUserShareView]
    group_shares: list[PluginGroupShareView]


class IntegrationOAuthStartRequest(BaseModel):
    organization: bool = False
    return_path: SafeOAuthReturnPath | None = None


class IntegrationOAuthStartResponse(BaseModel):
    authorization_url: str


class IntegrationOAuthCallbackRequest(BaseModel):
    code: str
    state: str
