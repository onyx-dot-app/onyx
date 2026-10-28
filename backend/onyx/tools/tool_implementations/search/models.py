from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchCycle, TimeFilter


class SearchContext(BaseModel):
    """Planning decisions from completed searches in the current turn."""

    model_config = ConfigDict(frozen=True)

    search_cycles: tuple[SearchCycle, ...] = ()
    cached_expansion: tuple[str | None, tuple[str, ...]] | None = None
    scope_decision_settled: bool = False
    time_filter: TimeFilter | None = None
    time_filter_computed: bool = False


class SearchPlanningResult(BaseModel):
    """New planning decisions from one successful retrieval, including zero hits."""

    model_config = ConfigDict(frozen=True)

    tool_call_id: str | None = None
    original_queries: tuple[str, ...]
    searched_sources: tuple[str, ...]
    cached_expansion: tuple[str | None, tuple[str, ...]] | None = None
    scope_decision_settled: bool = False
    time_filter: TimeFilter | None = None
    time_filter_computed: bool = False


class QueryExpansionAndScope(BaseModel):
    semantic_query: str | None
    keyword_queries: list[str]
    plan_scope: list[DocumentSource] | None
    scope_decision_settled: bool = False
    time_filter: TimeFilter | None = None
    time_filter_computed: bool = False


class SearchArguments(BaseModel):
    queries: list[str]
