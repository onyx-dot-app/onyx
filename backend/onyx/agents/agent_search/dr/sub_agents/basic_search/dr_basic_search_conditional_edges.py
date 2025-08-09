from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.states import QuestionInputState
from onyx.agents.agent_search.dr.sub_agents.states import (
    SubAgentInput,
)


def branching_router(state: SubAgentInput) -> list[Send | Hashable] | DRPath | str:
    return [
        Send(
            "act",
            QuestionInputState(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                question=query,
                log_messages=[],
                tool=DRPath.INTERNAL_SEARCH,
                active_source_types=state.active_source_types,
                time_budget=state.time_budget,
            ),
        )
        for parallelization_nr, query in enumerate(
            state.query_list[:MAX_DR_PARALLEL_SEARCH]
        )
    ]
