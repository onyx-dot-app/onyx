from typing import Any

from pydantic import BaseModel

from onyx.db.models import Tool


class ToolVisibilitySettings(BaseModel):
    """Configuration for tool visibility across different UI contexts."""

    chat_selectable: bool = True  # Whether tool appears in chat input bar dropdown
    agent_creation_selectable: bool = (
        True  # Whether tool appears in agent creation/default behavior pages
    )
    default_enabled: bool = False  # Whether tool is enabled by default
    expose_to_frontend: bool = True  # Whether tool should be sent to frontend at all


# Centralized configuration for tool visibility across different contexts
# This allows for easy extension with new tools that need custom visibility rules
TOOL_VISIBILITY_CONFIG: dict[str, ToolVisibilitySettings] = {
    "OpenURLTool": ToolVisibilitySettings(
        chat_selectable=False,
        agent_creation_selectable=True,
        default_enabled=True,
        expose_to_frontend=True,
    ),
    "OktaProfileTool": ToolVisibilitySettings(
        chat_selectable=False,
        agent_creation_selectable=False,
        default_enabled=False,
        expose_to_frontend=False,  # Completely hidden from frontend
    ),
    # Future tools can be added here with custom visibility rules
}


def should_expose_tool_to_fe(tool: Tool) -> bool:
    """Return True when the given tool should be sent to the frontend."""
    if tool.in_code_tool_id is None:
        # Custom tools are always exposed to frontend
        return True

    config = TOOL_VISIBILITY_CONFIG.get(tool.in_code_tool_id)
    return config.expose_to_frontend if config else True


def is_chat_selectable(tool: Tool) -> bool:
    """Return True if the tool should appear in the chat input bar dropdown.

    Tools can be excluded from the chat dropdown while remaining available
    in agent creation and configuration pages.
    """
    if tool.in_code_tool_id is None:
        # Custom tools are always chat selectable
        return True

    config = TOOL_VISIBILITY_CONFIG.get(tool.in_code_tool_id)

    return config.chat_selectable if config else True


def is_agent_creation_selectable(tool: Tool) -> bool:
    """Return True if the tool should appear in agent creation/default behavior pages.

    Most tools should be visible in these admin contexts.
    """
    if tool.in_code_tool_id is None:
        # Custom tools are always agent creation selectable
        return True

    config = TOOL_VISIBILITY_CONFIG.get(tool.in_code_tool_id)
    return config.agent_creation_selectable if config else True


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

    @classmethod
    def from_model(cls, tool: Tool) -> "ToolSnapshot":
        return cls(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            definition=tool.openapi_schema,
            display_name=tool.display_name or tool.name,
            in_code_tool_id=tool.in_code_tool_id,
            custom_headers=tool.custom_headers,
            passthrough_auth=tool.passthrough_auth,
            mcp_server_id=tool.mcp_server_id,
            user_id=str(tool.user_id) if tool.user_id else None,
            oauth_config_id=tool.oauth_config_id,
            oauth_config_name=tool.oauth_config.name if tool.oauth_config else None,
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
