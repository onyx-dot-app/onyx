"""Models for default assistant configuration API."""

from pydantic import BaseModel
from pydantic import Field


class DefaultAssistantConfiguration(BaseModel):
    """Simplified view of default assistant configuration for admin UI."""

    tool_ids: list[int] = Field(
        default_factory=list, description="List of enabled tool IDs"
    )
    system_prompt: str = Field(
        ..., description="System prompt (instructions) for the assistant"
    )


class DefaultAssistantUpdateRequest(BaseModel):
    """Request model for updating default assistant configuration."""

    tool_ids: list[int] | None = Field(
        default=None,
        description="List of tool IDs to enable. Must be Web Search, Internal Search, or Image Generation",
    )
    system_prompt: str | None = Field(
        default=None,
        description="New system prompt (instructions). Can be empty string but not null",
    )


class AvailableTool(BaseModel):
    """Available built-in tool that can be enabled on the default assistant."""

    id: int = Field(..., description="Database ID for the tool")
    in_code_tool_id: str = Field(
        ..., description="Stable in-code identifier for the tool"
    )
    display_name: str = Field(..., description="Human-friendly name for the tool")
    description: str = Field(..., description="Description of the tool")
    is_available: bool = Field(
        ..., description="Whether the tool is currently usable (configured)"
    )
