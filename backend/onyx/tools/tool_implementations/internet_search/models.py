from typing import Any
from typing import Literal

from pydantic import BaseModel

from onyx.context.search.models import InferenceSection


class InternetSearchResponseSummary(BaseModel):
    query: str
    top_sections: list[InferenceSection]


class InternetSearchResult(BaseModel):
    title: str
    link: str
    full_content: str
    published_date: str | None = None
    rag_context: str | None = None


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
