from typing import Any

from pydantic import BaseModel

from onyx.db.models import Tool


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
    target_persona_id: int | None = None

    @classmethod
    def from_model(cls, tool: Tool) -> "ToolSnapshot":
        return cls(
            id=tool.id,
            name=tool.name,
            description=tool.description,
            definition=tool.openapi_schema,
            target_persona_id=tool.target_persona_id,
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
