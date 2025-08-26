from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import (
    SubAgentInput,
)


def branching_router(state: SubAgentInput) -> list[Send | Hashable]:
    return [
        Send(
            "act",
            BranchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                branch_question=query,
                context="",
                active_source_types=state.active_source_types,
                tools_used=state.tools_used,
                available_tools=state.available_tools,
            ),
        )
        for parallelization_nr, query in enumerate(
            state.query_list[:1]  # no parallel call for now
        )
    ]
