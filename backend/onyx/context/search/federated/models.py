from datetime import datetime

from pydantic import BaseModel


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
