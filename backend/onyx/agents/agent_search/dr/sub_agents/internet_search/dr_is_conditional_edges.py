from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import FetchInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput


def branching_router(state: SubAgentInput) -> list[Send | Hashable]:
    return [
        Send(
            "search",
            BranchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                current_step_nr=state.current_step_nr,
                branch_question=query,
                context="",
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
            ),
        )
        for parallelization_nr, query in enumerate(
            state.query_list[:MAX_DR_PARALLEL_SEARCH]
        )
    ]


def fetch_router(state: SubAgentInput) -> list[Send | Hashable]:
    return [
        Send(
            "fetch",
            FetchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=0,
                branch_question="",
                context=state.context,
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
                urls_to_open=state.urls_to_open,
            ),
        )
    ]
