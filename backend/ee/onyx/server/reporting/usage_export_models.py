from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class FlowType(str, Enum):
    CHAT = "chat"
    SLACK = "slack"


class ChatMessageSkeleton(BaseModel):
    message_id: int
    chat_session_id: UUID
    user_id: str | None
    flow_type: FlowType
    time_sent: datetime
    assistant_name: str | None
    user_email: str | None
    number_of_tokens: int
    # Display name of the LLM that generated the assistant reply paired with
    # this user message. None if no assistant reply exists yet or the model
    # was never recorded.
    llm_model: str | None


class UserSkeleton(BaseModel):
    user_id: str
    is_active: bool


class UsageReportMetadata(BaseModel):
    report_name: str
    requestor: str | None
    time_created: datetime
    period_from: datetime | None  # None = All time
    period_to: datetime | None
