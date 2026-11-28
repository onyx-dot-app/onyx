from enum import Enum
from typing import Any

from pydantic import BaseModel


class NotionSearchObjectType(str, Enum):
    """The object type a search returns (the ``filter.value`` of ``search``)."""

    PAGE = "page"
    # Search returns data sources, not databases, since API version 2025-09-03.
    DATA_SOURCE = "data_source"


class NotionSearchResponse(BaseModel):
    """One page of results from the Notion search API."""

    results: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool = False
