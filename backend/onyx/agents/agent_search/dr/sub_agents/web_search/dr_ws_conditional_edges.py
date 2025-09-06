from collections.abc import Hashable

from langgraph.types import Send

from onyx.agents.agent_search.dr.constants import MAX_DR_PARALLEL_SEARCH
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.web_search.states import FetchInput
from onyx.agents.agent_search.dr.sub_agents.web_search.states import (
    InternetSearchInput,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.states import SummarizeInput


def branching_router(state: SubAgentInput) -> list[Send | Hashable]:
    return [
        Send(
            "search",
            InternetSearchInput(
                iteration_nr=state.iteration_nr,
                current_step_nr=state.current_step_nr,
                parallelization_nr=parallelization_nr,
                query_list=[query],
                branch_question=query,
                context="",
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
                results_to_open=[],
            ),
        )
        for parallelization_nr, query in enumerate(
            state.query_list[:MAX_DR_PARALLEL_SEARCH]
        )
    ]


def fetch_router(state: InternetSearchInput) -> list[Send | Hashable]:
    branch_questions_to_urls = state.branch_questions_to_urls
    return [
        Send(
            "fetch",
            FetchInput(
                iteration_nr=state.iteration_nr,
                urls_to_open=[url],
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
                current_step_nr=state.current_step_nr,
                branch_questions_to_urls=branch_questions_to_urls,
                raw_documents=state.raw_documents,
            ),
        )
        for url in set(
            url for urls in branch_questions_to_urls.values() for url in urls
        )
    ]


def summarize_router(state: InternetSearchInput) -> list[Send | Hashable]:
    branch_questions_to_urls = state.branch_questions_to_urls
    return [
        Send(
            "summarize",
            SummarizeInput(
                iteration_nr=state.iteration_nr,
                raw_documents=state.raw_documents,
                branch_questions_to_urls=branch_questions_to_urls,
                branch_question=branch_question,
                tools_used=state.tools_used,
                available_tools=state.available_tools,
                assistant_system_prompt=state.assistant_system_prompt,
                assistant_task_prompt=state.assistant_task_prompt,
                current_step_nr=state.current_step_nr,
            ),
        )
        for branch_question in branch_questions_to_urls.keys()
    ]
