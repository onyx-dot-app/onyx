from datetime import datetime

from pydantic import BaseModel


class SlackMessage(BaseModel):
    document_id: str
    texts: list[str]
    highlighted_texts: set[str]
    link: str
    semantic_identifier: str
    metadata: dict[str, str | list[str]]
    timestamp: datetime
    score: float
    recency_bias: float
