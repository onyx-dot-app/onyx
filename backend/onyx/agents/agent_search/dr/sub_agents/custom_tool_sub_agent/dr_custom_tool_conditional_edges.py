from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_states import (
    BranchInput,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_states import (
    SubAgentInput,
)


def branching_router(state: SubAgentInput) -> list[Send | Hashable] | DRPath | str:
    # TODO: should this be moved to dr.conditional_edges.py?
    return [
        Send(
            "act",
            BranchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                branch_question=query,
                main_question="",
                context="",
            ),
        )
        for parallelization_nr, query in enumerate(
            state.query_list[:MAX_DR_PARALLEL_SEARCH]
        )
    ]
