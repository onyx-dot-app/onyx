"""Tool visibility configuration and utility functions."""

from pydantic import BaseModel

from onyx.db.models import Tool
from onyx.tools.constants import OPEN_URL_TOOL_ID

# Tool class name constant for OktaProfileTool (not in main constants.py as it's hidden)
OKTA_PROFILE_TOOL_ID = "OktaProfileTool"


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
    OPEN_URL_TOOL_ID: ToolVisibilitySettings(
        chat_selectable=False,
        agent_creation_selectable=True,
        default_enabled=True,
        expose_to_frontend=True,
    ),
    OKTA_PROFILE_TOOL_ID: ToolVisibilitySettings(
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


def get_tool_visibility_config(tool: Tool) -> ToolVisibilitySettings | None:
    """Get visibility configuration for a tool, or None if not configured."""
    if tool.in_code_tool_id is None:
        return None
    return TOOL_VISIBILITY_CONFIG.get(tool.in_code_tool_id)
