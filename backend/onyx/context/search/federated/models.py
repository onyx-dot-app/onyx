from datetime import datetime

from pydantic import BaseModel


class SlackMessage(BaseModel):
    document_id: str
    link: str
    metadata: dict[str, str | list[str]]
    timestamp: datetime
    recency_bias: float
    semantic_identifier: str
    text: str
    highlighted_texts: set[str]
    slack_score: float
