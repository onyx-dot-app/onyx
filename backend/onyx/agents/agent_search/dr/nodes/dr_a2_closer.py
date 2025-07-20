from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.access.access import get_acl_for_user
from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.calculations import (
    get_answer_generation_documents,
)
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import relevance_from_docs
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import ExtendedToolResponse
from onyx.context.search.enums import SearchType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.prompts.dr_prompts import FINAL_ANSWER_PROMPT
from onyx.tools.tool_implementations.search.search_tool import IndexFilters
from onyx.tools.tool_implementations.search.search_tool import SearchQueryInfo
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def closer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate:
    """
    LangGraph node to close the DR process and finalize the answer.
    """

    node_start_time = datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question[0]
    if not base_question:
        raise ValueError("Question is required for closer")

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    aggregated_context = aggregate_context(state.iteration_responses)
    iteration_responses_string = aggregated_context.context
    all_cited_documents = aggregated_context.cited_documents

    # Stream out docs - TODO: Improve this with new frontend

    user = (
        graph_config.tooling.search_tool.user
        if graph_config.tooling.search_tool
        else None
    )

    if not user:
        raise ValueError("User is not set")

    search_tool = graph_config.tooling.search_tool
    if search_tool is None:
        raise ValueError("Search tool is not set")

    answer_generation_documents = get_answer_generation_documents(
        relevant_docs=all_cited_documents,
        context_documents=[],
        original_question_docs=[],
        max_docs=40,
    )

    relevance_list = relevance_from_docs(
        answer_generation_documents.streaming_documents
    )

    assert graph_config.tooling.search_tool is not None

    with get_session_with_current_tenant() as graph_db_session:
        user_acl = list(get_acl_for_user(user, graph_db_session))

    for tool_response in yield_search_responses(
        query=base_question,
        get_retrieved_sections=lambda: answer_generation_documents.context_documents,
        get_final_context_sections=lambda: answer_generation_documents.context_documents,
        search_query_info=SearchQueryInfo(
            predicted_search=SearchType.KEYWORD,
            # acl here is empty, because the searach alrady happened and
            # we are streaming out the results.
            final_filters=IndexFilters(access_control_list=user_acl),
            recency_bias_multiplier=1.0,
        ),
        get_section_relevance=lambda: relevance_list,
        search_tool=graph_config.tooling.search_tool,
    ):
        write_custom_event(
            "tool_response",
            ExtendedToolResponse(
                id=tool_response.id,
                response=tool_response.response,
                level=0,
                level_question_num=0,  # 0, 0 is the base question
            ),
            writer,
        )

    # Generate final answer

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece="\n\n\nFINAL ANSWER:\n\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    final_answer_prompt = (
        FINAL_ANSWER_PROMPT.replace("---base_question---", base_question)
        .replace("---iteration_responses_string---", iteration_responses_string)
        .replace("---chat_history_string---", chat_history_string)
    )

    try:
        streamed_output = run_with_timeout(
            80,
            lambda: stream_llm_answer(
                llm=graph_config.tooling.primary_llm,
                prompt=final_answer_prompt,
                event_name="basic_response",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=60,
                max_tokens=None,
            ),
        )

        final_answer = "".join(streamed_output[0])
    except Exception as e:
        raise ValueError(f"Error in consolidate_research: {e}")

    dispatch_main_answer_stop_info(level=0, writer=writer)

    return FinalUpdate(
        final_answer=final_answer,
        all_cited_documents=all_cited_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
