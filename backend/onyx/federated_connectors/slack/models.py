from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SlackEntities(BaseModel):
    """Pydantic model for Slack federated search entities."""

    # Channel filtering
    search_all_channels: bool = Field(
        default=True,
        description="Search all accessible channels. If not set, must specify channels below.",
    )
    channels: Optional[list[str]] = Field(
        default=None,
        description="List of Slack channel names to search across.",
    )
    exclude_channels: Optional[list[str]] = Field(
        default=None,
        description="List of channel names or patterns to exclude e.g. 'private-*, customer-*, secure-channel'.",
    )

    # Direct message filtering
    include_dm: bool = Field(
        default=True,
        description="Include user direct messages in search results",
    )
    include_group_dm: bool = Field(
        default=True,
        description="Include group direct messages (multi-person DMs) in search results",
    )

    # Private channel filtering
    include_private_channels: bool = Field(
        default=True,
        description="Include private channels in search results (user must have access)",
    )

    # Date range filtering
    default_search_days: int = Field(
        default=30,
        description="Maximum number of days to search back. Increasing this value degrades answer quality.",
    )

    # Message count per slack request
    max_messages_per_query: int = Field(
        default=10,
        description=(
            "Maximum number of messages to retrieve per search query. "
            "Higher values increase API calls and may trigger rate limits."
        ),
    )

    @field_validator("default_search_days")
    @classmethod
    def validate_default_search_days(cls, v: int) -> int:
        """Validate default_search_days is positive and reasonable"""
        if v < 1:
            raise ValueError("default_search_days must be at least 1")
        if v > 365:
            raise ValueError("default_search_days cannot exceed 365 days")
        return v

    @field_validator("max_messages_per_query")
    @classmethod
    def validate_max_messages_per_query(cls, v: int) -> int:
        """Validate max_messages_per_query is positive and reasonable"""
        if v < 1:
            raise ValueError("max_messages_per_query must be at least 1")
        if v > 100:
            raise ValueError("max_messages_per_query cannot exceed 100")
        return v

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Validate each channel is a non-empty string"""
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("channels must be a list")
            for channel in v:
                if not isinstance(channel, str) or not channel.strip():
                    raise ValueError("Each channel must be a non-empty string")
        return v

    @field_validator("exclude_channels")
    @classmethod
    def validate_exclude_patterns(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Validate each exclude pattern is a non-empty string"""
        if v is None:
            return v

        for pattern in v:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError("Each exclude pattern must be a non-empty string")

        return v

    @model_validator(mode="after")
    def validate_channel_config(self) -> "SlackEntities":
        """Validate search_all_channels configuration"""
        # If search_all_channels is False, channels list must be provided
        if not self.search_all_channels:
            if self.channels is None or len(self.channels) == 0:
                raise ValueError(
                    "Must specify at least one channel when search_all_channels is False"
                )

        return self


class SlackCredentials(BaseModel):
    """Slack federated connector credentials."""

    client_id: str = Field(..., description="Slack app client ID")
    client_secret: str = Field(..., description="Slack app client secret")

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Client ID cannot be empty")
        return v.strip()

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Client secret cannot be empty")
        return v.strip()
