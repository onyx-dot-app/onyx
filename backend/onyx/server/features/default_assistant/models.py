"""Models for default assistant configuration API."""

from pydantic import BaseModel
from pydantic import Field


# Valid built-in tool IDs that can be toggled for the default assistant
VALID_BUILTIN_TOOL_IDS = ["SearchTool", "InternetSearchTool", "ImageGenerationTool"]


class DefaultAssistantConfiguration(BaseModel):
    """Simplified view of default assistant configuration for admin UI."""

    tool_ids: list[str] = Field(
        default_factory=list, description="List of enabled tool IDs"
    )
    system_prompt: str = Field(
        ..., description="System prompt (instructions) for the assistant"
    )


class DefaultAssistantUpdateRequest(BaseModel):
    """Request model for updating default assistant configuration."""

    tool_ids: list[str] | None = Field(
        default=None,
        description="List of tool IDs to enable. If provided, must be from VALID_BUILTIN_TOOL_IDS",
    )
    system_prompt: str | None = Field(
        default=None,
        description="New system prompt (instructions). Can be empty string but not null",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "tool_ids": ["SearchTool", "InternetSearchTool"],
                "system_prompt": "You are a helpful assistant that provides accurate information.",
            }
        }
