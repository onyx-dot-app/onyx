from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.models import (
    ExpandedRetrievalResult,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.operations import (
    calculate_sub_question_retrieval_stats,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalUpdate,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import ExtendedToolResponse
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses


def format_results(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> ExpandedRetrievalUpdate:
    level, question_nr = parse_question_id(state.sub_question_id or "0_0")
    query_infos = [
        result.query_info
        for result in state.expanded_retrieval_results
        if result.query_info is not None
    ]
    if len(query_infos) == 0:
        raise ValueError("No query info found")

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    # main question docs will be sent later after aggregation and deduping with sub-question docs
    if not (level == 0 and question_nr == 0):
        if len(state.reranked_documents) > 0:
            stream_documents = state.reranked_documents
        else:
            # The sub-question is used as the last query. If no verified documents are found, stream
            # the top 3 for that one. We may want to revisit this.
            stream_documents = state.expanded_retrieval_results[-1].search_results[:3]
        for tool_response in yield_search_responses(
            query=state.question,
            reranked_sections=state.retrieved_documents,  # TODO: rename params. (sections pre-merging here.)
            final_context_sections=stream_documents,
            search_query_info=query_infos[0],  # TODO: handle differing query infos?
            get_section_relevance=lambda: None,  # TODO: add relevance
            search_tool=agent_a_config.search_tool,
        ):
            dispatch_custom_event(
                "tool_response",
                ExtendedToolResponse(
                    id=tool_response.id,
                    response=tool_response.response,
                    level=level,
                    level_question_nr=question_nr,
                ),
            )
    sub_question_retrieval_stats = calculate_sub_question_retrieval_stats(
        verified_documents=state.verified_documents,
        expanded_retrieval_results=state.expanded_retrieval_results,
    )

    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = AgentChunkStats()
    # else:
    #    sub_question_retrieval_stats = [sub_question_retrieval_stats]

    return ExpandedRetrievalUpdate(
        expanded_retrieval_result=ExpandedRetrievalResult(
            expanded_queries_results=state.expanded_retrieval_results,
            all_documents=state.reranked_documents,
            sub_question_retrieval_stats=sub_question_retrieval_stats,
        ),
    )
