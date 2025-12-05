from typing import Any

from pydantic import BaseModel

from onyx.db.models import Tool
from onyx.server.features.tool.tool_visibility import get_tool_visibility_config


class ToolSnapshot(BaseModel):
    id: int
    name: str
    description: str
    definition: dict[str, Any] | None
    display_name: str
    in_code_tool_id: str | None
    custom_headers: list[Any] | None
    passthrough_auth: bool
    mcp_server_id: int | None = None
    user_id: str | None = None
    oauth_config_id: int | None = None
    oauth_config_name: str | None = None
    enabled: bool = True

    # Visibility settings computed from TOOL_VISIBILITY_CONFIG
    chat_selectable: bool = True
    agent_creation_selectable: bool = True
    default_enabled: bool = False

    @classmethod
    def from_model(cls, tool: Tool) -> "ToolSnapshot":
        # Get visibility config for this tool
        config = get_tool_visibility_config(tool)

        return cls(
            id=tool.id,
            name=tool.name,
            description=tool.description or "",
            definition=tool.openapi_schema,
            display_name=tool.display_name or tool.name,
            in_code_tool_id=tool.in_code_tool_id,
            custom_headers=tool.custom_headers,
            passthrough_auth=tool.passthrough_auth,
            mcp_server_id=tool.mcp_server_id,
            user_id=str(tool.user_id) if tool.user_id else None,
            oauth_config_id=tool.oauth_config_id,
            oauth_config_name=tool.oauth_config.name if tool.oauth_config else None,
            enabled=tool.enabled,
            # Populate visibility settings from config or use defaults
            chat_selectable=config.chat_selectable if config else True,
            agent_creation_selectable=(
                config.agent_creation_selectable if config else True
            ),
            default_enabled=config.default_enabled if config else False,
        )


class Header(BaseModel):
    key: str
    value: str


class CustomToolCreate(BaseModel):
    name: str
    description: str | None = None
    definition: dict[str, Any]
    custom_headers: list[Header] | None = None
    passthrough_auth: bool
    oauth_config_id: int | None = None


class CustomToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None
    custom_headers: list[Header] | None = None
    passthrough_auth: bool | None = None
    oauth_config_id: int | None = None
