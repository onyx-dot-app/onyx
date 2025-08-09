from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.constants import MAX_NUM_CLOSER_SUGGESTIONS
from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import TestInfoCompleteResponse
from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.dr.utils import get_prompt_question
from onyx.agents.agent_search.dr.utils import parse_plan_to_dict
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_citation_format_list
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import ExtendedToolResponse
from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import SearchType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.prompts.dr_prompts import FINAL_ANSWER_PROMPT
from onyx.prompts.dr_prompts import TEST_INFO_COMPLETE_PROMPT
from onyx.tools.tool_implementations.search.search_tool import IndexFilters
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def save_iteration(
    message_id: int, state: MainState, aggregated_context: AggregatedDRContext
):
    # TODO: generate plan as dict in the first place
    plan_of_record = state.plan_of_record.plan if state.plan_of_record else ""
    plan_of_record_dict = parse_plan_to_dict(plan_of_record)

    with get_session_with_current_tenant() as db_session:
        chat_message = (
            db_session.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        )
        if not chat_message:
            raise ValueError("Chat message with id not found")  # should never happen

        chat_message.research_type = ResearchType.THOUGHTFUL  # FIXME: joachim
        chat_message.research_plan = plan_of_record_dict

        for iteration_preparation in state.iteration_instructions:
            research_agent_iteration_step = ResearchAgentIteration(
                primary_question_id=message_id,
                reasoning=iteration_preparation.reasoning,
                purpose=iteration_preparation.purpose,
                iteration_nr=iteration_preparation.iteration_nr,
                created_at=datetime.now(),
            )
            db_session.add(research_agent_iteration_step)

        for iteration_answer in aggregated_context.global_iteration_responses:
            research_agent_iteration_sub_step = ResearchAgentIterationSubStep(
                primary_question_id=message_id,
                parent_question_id=None,
                iteration_nr=iteration_answer.iteration_nr,
                iteration_sub_step_nr=iteration_answer.parallelization_nr,
                sub_step_instructions=iteration_answer.question,
                sub_step_tool_id=iteration_answer.tool_id,
                sub_answer=iteration_answer.answer,
                reasoning=iteration_answer.reasoning,
                claims=iteration_answer.claims,
                cited_doc_results=create_citation_format_list(
                    [doc for doc in iteration_answer.cited_documents.values()]
                ),
                additional_data=iteration_answer.additional_data,
                created_at=datetime.now(),
            )
            db_session.add(research_agent_iteration_sub_step)

        db_session.commit()


def closer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate | OrchestrationUpdate:
    """
    LangGraph node to close the DR process and finalize the answer.
    """

    node_start_time = datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question
    if not base_question:
        raise ValueError("Question is required for closer")

    time_budget = graph_config.behavior.time_budget

    clarification = state.clarification
    prompt_question = get_prompt_question(base_question, clarification)

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    if time_budget == ResearchType.THOUGHTFUL:
        aggregated_context = aggregate_context(
            state.iteration_responses,
            include_documents=True,
            include_answers_claims=True,
        )
    else:
        aggregated_context = aggregate_context(
            state.iteration_responses,
            include_documents=True,
        )

    iteration_responses_string = aggregated_context.context
    all_cited_documents = aggregated_context.cited_documents

    num_closer_suggestions = state.num_closer_suggestions

    if (
        num_closer_suggestions < MAX_NUM_CLOSER_SUGGESTIONS
        and time_budget == ResearchType.DEEP
    ):
        if time_budget == ResearchType.DEEP:
            test_info_complete_prompt = TEST_INFO_COMPLETE_PROMPT.build(
                base_question=prompt_question,
                questions_answers_claims=iteration_responses_string,
                chat_history_string=chat_history_string,
                high_level_plan=(
                    state.plan_of_record.plan
                    if state.plan_of_record
                    else "No plan available"
                ),
            )

            test_info_complete_json = invoke_llm_json(
                llm=graph_config.tooling.primary_llm,
                prompt=test_info_complete_prompt,
                schema=TestInfoCompleteResponse,
                timeout_override=40,
                # max_tokens=1000,
            )

            if test_info_complete_json.complete:
                pass

            else:
                return OrchestrationUpdate(
                    query_path=[DRPath.ORCHESTRATOR],
                    query_list=[],
                    log_messages=[
                        get_langgraph_node_log_string(
                            graph_component="main",
                            node_name="closer",
                            node_start_time=node_start_time,
                        )
                    ],
                    gaps=test_info_complete_json.gaps,
                    num_closer_suggestions=num_closer_suggestions + 1,
                )

    # Stream out docs - TODO: Improve this with new frontend
    write_custom_event(
        "tool_response",
        ExtendedToolResponse(
            id=SEARCH_RESPONSE_SUMMARY_ID,
            response=SearchResponseSummary(
                rephrased_query=base_question,
                top_sections=all_cited_documents,
                predicted_flow=QueryFlow.QUESTION_ANSWER,
                predicted_search=SearchType.KEYWORD,  # unused
                final_filters=IndexFilters(access_control_list=None),  # unused
                recency_bias_multiplier=1.0,  # unused
            ),
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

    final_answer_prompt = FINAL_ANSWER_PROMPT.build(
        base_question=prompt_question,
        iteration_responses_string=iteration_responses_string,
        chat_history_string=chat_history_string,
    )

    try:
        streamed_output = run_with_timeout(
            240,
            lambda: stream_llm_answer(
                llm=graph_config.tooling.primary_llm,
                prompt=final_answer_prompt,
                event_name="basic_response",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=60,
                # kens=None,
            ),
        )

        final_answer = "".join(streamed_output[0])
    except Exception as e:
        raise ValueError(f"Error in consolidate_research: {e}")

    dispatch_main_answer_stop_info(level=0, writer=writer)

    # Log the research agent steps
    save_iteration(graph_config.persistence.message_id, state, aggregated_context)

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
