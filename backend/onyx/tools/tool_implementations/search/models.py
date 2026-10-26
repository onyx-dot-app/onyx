from pydantic import BaseModel

from onyx.context.search.models import SearchCycle, TimeFilter


class SearchToolState(BaseModel):
    search_cycles: list[SearchCycle]
    cached_expansion: tuple[str | None, list[str]] | None
    scope_decision_settled: bool
    time_filter: TimeFilter | None
    time_filter_computed: bool


class SearchArguments(BaseModel):
    queries: list[str]
