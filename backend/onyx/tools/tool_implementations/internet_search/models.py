from datetime import datetime
from enum import Enum
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import field_validator

from onyx.context.search.models import InferenceSection

MAX_CONTENT_LENGTH = 1_048_576


class InternetSearchResponseSummary(BaseModel):
    query: str
    top_sections: list[InferenceSection]


class InternetSearchResult(BaseModel):
    title: str
    link: str
    full_content: str
    published_date: datetime | None = None
    rag_context: str | None = None

    @field_validator("full_content")
    @classmethod
    def validate_content_length(cls, v: str) -> str:
        """Truncate content if it exceeds maximum length to prevent memory issues."""
        if len(v) > MAX_CONTENT_LENGTH:
            return v[:MAX_CONTENT_LENGTH] + "... [Content truncated due to length]"
        return v


class ProviderType(Enum):
    """Enum for internet search provider types"""

    BING = "bing"
    EXA = "exa"


class ProviderConfig(BaseModel):
    api_key: str | None = None
    api_base: str
    headers: dict[str, str]
    query_param_name: str
    num_results_param: str
    search_params: dict[str, Any]
    request_method: Literal["GET", "POST"]
    results_path: list[str]
    result_mapping: dict[str, str]
    global_fields: dict[str, list[str]] = {}
