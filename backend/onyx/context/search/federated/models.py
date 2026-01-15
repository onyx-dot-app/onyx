from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel

from onyx.onyxbot.slack.models import ChannelType


class ChannelMetadata(TypedDict):
    """Type definition for cached channel metadata."""

    name: str
    type: ChannelType
    is_private: bool
    is_member: bool


class SlackMessage(BaseModel):
    document_id: str
    channel_id: str
    message_id: str
    thread_id: str | None
    link: str
    metadata: dict[str, str | list[str]]
    timestamp: datetime
    recency_bias: float
    semantic_identifier: str
    text: str
    highlighted_texts: set[str]
    slack_score: float
