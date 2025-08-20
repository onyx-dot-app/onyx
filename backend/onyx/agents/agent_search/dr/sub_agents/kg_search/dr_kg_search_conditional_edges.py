from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput


def branching_router(state: SubAgentInput) -> list[Send | Hashable]:
    return [
        Send(
            "act",
            BranchInput(
                iteration_nr=state.iteration_nr,
                parallelization_nr=parallelization_nr,
                branch_question=query,
                context="",
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
            ),
        )
        for parallelization_nr, query in enumerate(
            state.query_list[:1]  # no parallel search for now
        )
    ]
