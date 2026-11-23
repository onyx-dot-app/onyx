from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, InstanceOf

from onyx.db.enums import (
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    MCPTransport,
)
from onyx.external_apps.providers.base import ExternalAppProvider
from onyx.skills.models import PluginNeed


class IntegrationActionSpec(BaseModel):
    """One action as its kind finds it. The action sync writes it to
    ``integration_action``, keyed by ``key``."""

    model_config = ConfigDict(frozen=True)

    key: str
    source: IntegrationActionSource
    display_name: str
    description: str | None
    read_only: bool | None
    default_policy: IntegrationActionPolicyValue
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    http_method: str | None = None
    path_template: str | None = None


class MatchedIntegrationAction(BaseModel):
    """One action that a proxied request calls, with the default policy of the
    action. The caller applies the stored policies."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    action_key: str
    display_name: str
    description: str
    default_policy: IntegrationActionPolicyValue


class RequestMatch(BaseModel):
    """What a kind finds in a proxied request for its integration. An empty
    ``actions`` is an MCP protocol request that calls no action."""

    model_config = ConfigDict(frozen=True)

    actions: list[MatchedIntegrationAction]
    # The length of the URL path prefix that matched. When two MCP servers
    # share a host, the longest prefix wins.
    path_prefix_length: int = 0


class McpServerConfig(BaseModel):
    """The settings of an ``mcp_server`` integration, from its ``mcp_server`` row."""

    model_config = ConfigDict(frozen=True)

    mcp_server_id: int
    server_url: str
    transport: MCPTransport | None


class ApiShape(str, Enum):
    # An OpenAPI custom tool: the spec gives the actions.
    OPENAPI = "openapi"
    # An external app with a built-in provider: the catalog gives the actions.
    PRESET = "preset"
    # An external app with no provider: one action for all of its URLs.
    CUSTOM = "custom"


class ApiConfig(BaseModel):
    """The settings of an ``api`` integration, from its OpenAPI ``tool`` row or
    its ``external_app`` row."""

    model_config = ConfigDict(frozen=True)

    shape: ApiShape
    # Set for OPENAPI.
    tool_id: int | None = None
    openapi_spec: dict[str, Any] | None = None
    base_url: str | None = None
    # Set for PRESET and CUSTOM.
    app_type: ExternalAppType | None = None


IntegrationConfig = McpServerConfig | ApiConfig


class Preset(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The ``ExternalAppType`` value, e.g. "LINEAR".
    id: str
    app_type: ExternalAppType
    name: str
    provider: InstanceOf[ExternalAppProvider]


class LinkValue(str, Enum):
    """The setting of one action on an agent or a task link."""

    INHERIT = "inherit"
    ALLOW = "allow"
    ASK = "ask"
    BLOCKED = "blocked"


class EffectivePolicy(str, Enum):
    """What happens when a run calls an action."""

    ALLOW = "allow"
    ASK = "ask"
    BLOCKED = "blocked"


class ApprovalMode(str, Enum):
    """Who can answer an Ask in a run."""

    # A person sees the approval card.
    INTERACTIVE = "interactive"
    # A Slack or Discord bot run: no person can answer, so Ask is Blocked.
    NO_APPROVER = "no_approver"
    # An eval run: Ask runs with no question.
    RUN_WITHOUT_ASKING = "run_without_asking"


class ActionSettings(BaseModel):
    """The ``action_settings`` of a ``persona__integration`` or
    ``scheduled_task__integration`` row. ``{}`` inherits each action."""

    model_config = ConfigDict(frozen=True)

    default: LinkValue = LinkValue.INHERIT
    actions: dict[str, LinkValue] = {}

    def value_for(self, action_key: str) -> LinkValue:
        return self.actions.get(action_key, self.default)


class PolicyRows(BaseModel):
    """The stored policy rows of one integration, by action key. The empty
    key is the default row."""

    model_config = ConfigDict(frozen=True)

    admin: dict[str, IntegrationActionPolicyValue]
    user: dict[str, IntegrationActionPolicyValue]


class CallCredentials(BaseModel):
    """What one call of an integration action sends."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    auth_method: IntegrationAuthMethod | None
    # The connection row the credential comes from. None for no sign-in and
    # for the Onyx login.
    connection_id: int | None
    # The user of that connection; None for the organization connection.
    connection_user_id: UUID | None
    # The rendered header template, with the bearer token of a token method.
    headers: dict[str, str]
    # The fingerprint of the stored secret of that connection, so a late
    # rejection does not mark a key that replaced it.
    secret_fingerprint: str | None = None
    # When the bearer token of a token method expires; None when unknown.
    expires_at: datetime | None = None


class UsableIntegrationIds(BaseModel):
    """The integrations that an admin did not turn off, of one user."""

    model_config = ConfigDict(frozen=True)

    # The integrations that are on for the user.
    on: frozenset[int]
    # The integrations that the user has access to, on or off.
    accessible: frozenset[int]


class PersonaIntegrationLink(BaseModel):
    """An integration on an agent (``persona__integration``)."""

    integration_id: int
    action_settings: ActionSettings = ActionSettings()


class PersonaIntegrationSnapshot(PersonaIntegrationLink):
    integration_name: str


class PluginNeedState(str, Enum):
    ON = "on"
    TURN_ON = "turn_on"
    SIGN_IN = "sign_in"
    NO_ACCESS = "no_access"
    TURNED_OFF = "turned_off"
    NOT_ADDED = "not_added"
    MORE_THAN_ONE = "more_than_one"
    NOT_SUPPORTED = "not_supported"


class PluginNeedView(PluginNeed):
    model_config = ConfigDict(frozen=True)

    state: PluginNeedState
    integration_id: int | None


class NeedCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    available_count: int
    needed_count: int
