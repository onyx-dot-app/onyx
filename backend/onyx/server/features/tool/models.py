from typing import Any

from pydantic import BaseModel, Field

from onyx.db.models import Tool
from onyx.server.features.tool.tool_visibility import get_tool_visibility_config
from onyx.utils.encryption import mask_string


def mask_custom_headers(headers: list[Any] | None) -> list[Any] | None:
    """Mask header values for read paths. Header values commonly carry bearer
    tokens, so they are masked like every other secret the API returns. Tool
    execution reads the unmasked values from the db model, not from a snapshot.
    """
    if not headers:
        return headers

    masked: list[Any] = []
    for header in headers:
        if isinstance(header, dict) and isinstance(header.get("value"), str):
            masked.append({**header, "value": mask_string(header["value"])})
        else:
            masked.append(header)
    return masked


def _openapi_info(tool: Tool) -> dict[str, Any]:
    """The `info` block of an OpenAPI tool's schema; empty for other tools."""
    if tool.openapi_schema is None or tool.mcp_server_id is not None:
        return {}
    info = tool.openapi_schema.get("info")
    return info if isinstance(info, dict) else {}


def _schema_text(info: dict[str, Any], key: str) -> str:
    value = info.get(key)
    return value if isinstance(value, str) else ""


class ToolSnapshot(BaseModel):
    id: int
    name: str
    description: str
    # The stored values before the schema fallback. For an OpenAPI tool,
    # None means the schema's name or description applies.
    name_override: str | None = None
    description_override: str | None = None
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
    user_enabled_in_chat: bool = True
    default_chat_enabled: bool | None = Field(
        None,
        description="Whether this tool is selected for the default assistant.",
    )

    # Server-stamped affordance map; fail-closed empty (only the admin actions list stamps it).
    permissions: dict[str, bool] = Field(default_factory=dict)

    # Visibility settings computed from TOOL_VISIBILITY_CONFIG
    chat_selectable: bool = True
    agent_creation_selectable: bool = True
    default_enabled: bool = False

    @classmethod
    def from_model(
        cls, tool: Tool, *, permissions: dict[str, bool] | None = None
    ) -> "ToolSnapshot":
        # Get visibility config for this tool
        config = get_tool_visibility_config(tool)
        # An OpenAPI tool's stored name and description only override its
        # schema's; empty ones fall back to the schema.
        info = _openapi_info(tool)
        name = tool.name or _schema_text(info, "title")
        description = tool.description or _schema_text(info, "description")

        return cls(
            permissions=permissions or {},
            id=tool.id,
            name=name,
            description=description,
            name_override=tool.name or None,
            description_override=tool.description or None,
            definition=tool.openapi_schema,
            display_name=tool.display_name or name,
            in_code_tool_id=tool.in_code_tool_id,
            custom_headers=mask_custom_headers(tool.custom_headers),
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


class ToolUserPreferences(BaseModel):
    enabled_in_chat: bool


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
