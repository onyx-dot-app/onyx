from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.access.access import get_acl_for_user
from onyx.agents.agent_search.kb_search.graph_utils import rename_entities_in_answer
from onyx.agents.agent_search.kb_search.ops import research
from onyx.agents.agent_search.kb_search.states import FinalAnswerUpdate
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.calculations import (
    get_answer_generation_documents,
)
from onyx.agents.agent_search.shared_graph_utils.llm import get_answer_from_llm
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import relevance_from_docs
from onyx.configs.kg_configs import KG_RESEARCH_NUM_RETRIEVED_DOCS
from onyx.configs.kg_configs import KG_TIMEOUT_CONNECT_LLM_INITIAL_ANSWER_GENERATION
from onyx.context.search.enums import SearchType
from onyx.context.search.models import InferenceSection
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.prompts.kg_prompts import OUTPUT_FORMAT_NO_EXAMPLES_PROMPT
from onyx.prompts.kg_prompts import OUTPUT_FORMAT_NO_OVERALL_ANSWER_PROMPT
from onyx.tools.tool_implementations.search.search_tool import IndexFilters
from onyx.tools.tool_implementations.search.search_tool import SearchQueryInfo
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generate_answer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalAnswerUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.question

    final_answer: str | None = None

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

    # Close out previous streams of steps

    # DECLARE STEPS DONE

    ## MAIN ANSWER

    # identify whether documents have already been retrieved

    retrieved_docs: list[InferenceSection] = []
    for step_result in state.step_results:
        retrieved_docs += step_result.verified_reranked_documents

    # if still needed, get a search done and send the results to the UI

    if not retrieved_docs and state.source_document_results:
        assert graph_config.tooling.search_tool is not None
        retrieved_docs = cast(
            list[InferenceSection],
            research(
                question=question,
                kg_entities=[],
                kg_relationships=[],
                kg_sources=state.source_document_results[
                    :KG_RESEARCH_NUM_RETRIEVED_DOCS
                ],
                search_tool=graph_config.tooling.search_tool,
                kg_chunk_id_zero_only=True,
                inference_sections_only=True,
            ),
        )

    answer_generation_documents = get_answer_generation_documents(
        relevant_docs=retrieved_docs,
        context_documents=retrieved_docs,
        original_question_docs=retrieved_docs,
        max_docs=KG_RESEARCH_NUM_RETRIEVED_DOCS,
    )

    relevance_list = relevance_from_docs(
        answer_generation_documents.streaming_documents
    )

    assert graph_config.tooling.search_tool is not None

    with get_session_with_current_tenant() as graph_db_session:
        user_acl = list(get_acl_for_user(user, graph_db_session))

    for tool_response in yield_search_responses(
        query=question,
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
        # original document streaming
        pass

    # continue with the answer generation

    output_format = (
        state.output_format.value
        if state.output_format
        else "<you be the judge how to best present the data>"
    )

    # if deep path was taken:

    consolidated_research_object_results_str = (
        state.consolidated_research_object_results_str
    )
    # reference_results_str = (
    #     state.reference_results_str
    # )  # will not be part of LLM. Manually added to the answer

    # if simple path was taken:
    introductory_answer = state.query_results_data_str  # from simple answer path only
    if consolidated_research_object_results_str:
        research_results = consolidated_research_object_results_str
    else:
        research_results = ""

    if introductory_answer:
        output_format_prompt = (
            OUTPUT_FORMAT_NO_EXAMPLES_PROMPT.replace("---question---", question)
            .replace(
                "---introductory_answer---",
                rename_entities_in_answer(introductory_answer),
            )
            .replace("---output_format---", str(output_format) if output_format else "")
        )
    elif research_results and consolidated_research_object_results_str:
        output_format_prompt = (
            OUTPUT_FORMAT_NO_EXAMPLES_PROMPT.replace("---question---", question)
            .replace(
                "---introductory_answer---",
                rename_entities_in_answer(consolidated_research_object_results_str),
            )
            .replace("---output_format---", str(output_format) if output_format else "")
        )
    elif research_results and not consolidated_research_object_results_str:
        output_format_prompt = (
            OUTPUT_FORMAT_NO_OVERALL_ANSWER_PROMPT.replace("---question---", question)
            .replace("---output_format---", str(output_format) if output_format else "")
            .replace(
                "---research_results---", rename_entities_in_answer(research_results)
            )
        )
    elif consolidated_research_object_results_str:
        output_format_prompt = (
            OUTPUT_FORMAT_NO_EXAMPLES_PROMPT.replace("---question---", question)
            .replace("---output_format---", str(output_format) if output_format else "")
            .replace(
                "---research_results---", rename_entities_in_answer(research_results)
            )
        )
    else:
        raise ValueError("No research results or introductory answer provided")

    try:

        final_answer = get_answer_from_llm(
            llm=graph_config.tooling.primary_llm,
            prompt=output_format_prompt,
            stream=False,
            json_string_flag=False,
            timeout_override=KG_TIMEOUT_CONNECT_LLM_INITIAL_ANSWER_GENERATION,
        )

    except Exception as e:
        raise ValueError(f"Could not generate the answer. Error {e}")

    return FinalAnswerUpdate(
        final_answer=final_answer,
        retrieved_documents=answer_generation_documents.context_documents,
        step_results=[],
        remarks=[],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="query completed",
                node_start_time=node_start_time,
            )
        ],
    )
