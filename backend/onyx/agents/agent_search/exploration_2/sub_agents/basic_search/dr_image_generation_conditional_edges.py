from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.exploration_2.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.exploration_2.sub_agents.states import BranchInput
from onyx.agents.agent_search.exploration_2.sub_agents.states import SubAgentInput


def branching_router(state: SubAgentInput) -> list[Send | Hashable]:
    return [
        Send(
            "act",
            BranchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                branch_question=query_request.get("query"),
                source_filters=query_request.get("source_filters"),
                date_filter_start=query_request.get("date_filter_start"),
                date_filter_end=query_request.get("date_filter_end"),
                current_step_nr=state.current_step_nr,
                context="",
                active_source_types=state.active_source_types,
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
            ),
        )
        for parallelization_nr, query_request in enumerate(
            state.query_list[:MAX_DR_PARALLEL_SEARCH]
        )
    ]
