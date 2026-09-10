from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.sql.elements import ColumnElement

from onyx.db.models import UserUsage


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


def build_usage_upsert_values(
    statement: Insert,
) -> dict[str, ColumnElement[Any]]:
    return {
        "input_tokens": UserUsage.input_tokens + statement.excluded.input_tokens,
        "output_tokens": UserUsage.output_tokens + statement.excluded.output_tokens,
        "cache_read_tokens": (
            UserUsage.cache_read_tokens + statement.excluded.cache_read_tokens
        ),
        "cache_creation_tokens": (
            UserUsage.cache_creation_tokens + statement.excluded.cache_creation_tokens
        ),
        "cost_cents": UserUsage.cost_cents + statement.excluded.cost_cents,
    }
