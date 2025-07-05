from typing import Optional

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator


class SlackEntities(BaseModel):
    """Pydantic model for Slack federated search entities."""

    channels: Optional[list[str]] = Field(
        default=None, description="List of Slack channel names or IDs to search in"
    )
    include_dm: Optional[bool] = Field(
        default=False, description="Whether to include direct messages in the search"
    )

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("channels must be a list")
            for channel in v:
                if not isinstance(channel, str) or not channel.strip():
                    raise ValueError("Each channel must be a non-empty string")
        return v


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


class SlackTeamInfo(BaseModel):
    """Information about a Slack team/workspace."""

    id: str = Field(..., description="Team ID")
    name: str = Field(..., description="Team name")
    domain: Optional[str] = Field(default=None, description="Team domain")


class SlackUserInfo(BaseModel):
    """Information about a Slack user."""

    id: str = Field(..., description="User ID")
    team_id: Optional[str] = Field(default=None, description="Team ID")
    name: Optional[str] = Field(default=None, description="User name")
    email: Optional[str] = Field(default=None, description="User email")


class SlackSearchResult(BaseModel):
    """Individual search result from Slack."""

    channel: str = Field(..., description="Channel where the message was found")
    timestamp: str = Field(..., description="Message timestamp")
    user: Optional[str] = Field(default=None, description="User who sent the message")
    text: str = Field(..., description="Message text")
    permalink: Optional[str] = Field(
        default=None, description="Permalink to the message"
    )
    score: Optional[float] = Field(default=None, description="Search relevance score")

    # Additional context
    thread_ts: Optional[str] = Field(
        default=None, description="Thread timestamp if in a thread"
    )
    reply_count: Optional[int] = Field(
        default=None, description="Number of replies if it's a thread"
    )


class SlackSearchResponse(BaseModel):
    """Response from Slack federated search."""

    query: str = Field(..., description="The search query")
    total_count: int = Field(..., description="Total number of results")
    results: list[SlackSearchResult] = Field(..., description="Search results")
    next_cursor: Optional[str] = Field(
        default=None, description="Cursor for pagination"
    )

    # Metadata
    channels_searched: Optional[list[str]] = Field(
        default=None, description="Channels that were searched"
    )
    search_time_ms: Optional[int] = Field(
        default=None, description="Time taken to search in milliseconds"
    )
