from __future__ import annotations

import operator
from dataclasses import dataclass
from dataclasses import field
from typing import Annotated
from typing import List
from typing import Tuple
from typing import TypedDict

from langgraph.graph import add_messages

from onyx.agents.agent_search.core_state import CoreState


class OverallState(TypedDict):
    messages: Annotated[list, add_messages]
    search_query: Annotated[list, operator.add]
    onyx_research_result: Annotated[list, operator.add]
    sources_gathered: Annotated[list, operator.add]
    initial_search_query_count: int
    max_research_loops: int
    research_loop_count: int
    reasoning_model: str


class ReflectionState(TypedDict):
    is_sufficient: bool
    knowledge_gap: str
    follow_up_queries: Annotated[list, operator.add]
    research_loop_count: int
    number_of_ran_queries: int


class Query(TypedDict):
    query: str
    rationale: str


class QueryGenerationState(TypedDict):
    query_list: list[Query]


class OnyxSearchState(TypedDict):
    search_query: str
    id: str


class PlanExecute(TypedDict):
    input: str
    plan: List[str]
    past_steps: Annotated[List[Tuple], operator.add]
    response: str
    max_steps: int
    step_count: int


@dataclass(kw_only=True)
class SearchStateOutput:
    running_summary: str = field(default=None)  # Final report


class DeepResearchInput(CoreState):
    pass
