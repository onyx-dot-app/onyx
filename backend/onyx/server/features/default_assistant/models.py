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
        description="List of tool IDs to enable for the default assistant",
    )
    system_prompt: str | None = Field(
        default=None,
        description="New system prompt (instructions). Can be empty string but not null",
    )
