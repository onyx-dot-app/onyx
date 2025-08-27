from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
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
    urls_to_process = state.urls_to_open

    # If no URLs to process, return empty list to go directly to reducer
    if not urls_to_process:
        return []

    url_pairs = [
        list(pair) for pair in zip(urls_to_process[::2], urls_to_process[1::2])
    ]
    if len(urls_to_process) % 2 == 1:
        url_pairs.append([urls_to_process[-1]])

    return [
        Send(
            "fetch",
            BranchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                urls_to_open=url_pair,
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
                current_step_nr=state.current_step_nr,
            ),
        )
        for parallelization_nr, url_pair in enumerate(url_pairs)
    ]
