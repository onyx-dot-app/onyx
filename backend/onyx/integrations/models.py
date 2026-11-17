from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, InstanceOf

from onyx.db.enums import (
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    MCPTransport,
)
from onyx.external_apps.providers.base import ExternalAppProvider


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
