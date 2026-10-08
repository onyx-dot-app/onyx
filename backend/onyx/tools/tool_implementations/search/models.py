from pydantic import BaseModel

from onyx.secondary_llm_flows.source_filter import SearchCycle
from onyx.secondary_llm_flows.time_filter import TimeFilter


class SearchToolState(BaseModel):
    search_cycles: list[SearchCycle]
    cached_expansion: tuple[str | None, list[str]] | None
    scope_decision_settled: bool
    time_filter: TimeFilter | None
    time_filter_computed: bool
