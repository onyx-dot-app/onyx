from datetime import datetime

from pydantic import BaseModel


class LLMUsageRecord(BaseModel):
    model: str
    flow: str
    provider: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int = 0
    cost_cents: float
    window_start: datetime
