import re
from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import BaseSearchProcessingResponse
from onyx.agents.agent_search.dr.models import DRPath
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import SearchAnswer
from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import QuestionInputState
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection
from onyx.db.connector import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.prompts.dr_prompts import BASE_SEARCH_PROCESSING_PROMPT
from onyx.prompts.dr_prompts import BASIC_SEARCH_PROMPTS
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.utils.logger import setup_logger

logger = setup_logger()


def basic_search(
    state: QuestionInputState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> AnswerUpdate:
    """
    LangGraph node to perform a standard search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr

    branch_query = state.question
    if not branch_query:
        raise ValueError("branch_query is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query
    time_budget = graph_config.behavior.time_budget

    search_tool = graph_config.tooling.search_tool

    if search_tool is None:
        raise ValueError("search_tool must be provided for agentic search")

    # rewrite query and identify source types

    active_source_types_str = ", ".join(
        [source.value for source in state.active_source_types or []]
    )

    base_search_processing_prompt = BASE_SEARCH_PROCESSING_PROMPT.replace(
        "---active_source_types_str---", active_source_types_str
    ).replace("---branch_query---", branch_query)

    try:
        search_processing = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=base_search_processing_prompt,
            schema=BaseSearchProcessingResponse,
            timeout_override=5,
            max_tokens=100,
        )
    except Exception as e:
        logger.error(f"Could not process query: {e}")
        raise e

    rewritten_query = search_processing.rewritten_query

    implied_start_date = search_processing.time_filter

    # Validate time_filter format if it exists
    if implied_start_date:

        # Check if time_filter is in YYYY-MM-DD format
        date_pattern = r"^\d{4}-\d{2}-\d{2}$"
        if not re.match(date_pattern, implied_start_date):
            implied_time_filter = None
        else:
            implied_time_filter = datetime.strptime(implied_start_date, "%Y-%m-%d")

    specified_source_types: list[DocumentSource] | None = [
        DocumentSource(source_type)
        for source_type in search_processing.specified_source_types
    ]

    if specified_source_types is not None and len(specified_source_types) == 0:
        specified_source_types = None

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=(
                f"SUB-QUESTION {iteration_nr}.{parallelization_nr} "
                f"(SEARCH): {branch_query}\n\n"
                f"REWRITTEN QUERY: {rewritten_query}\n\n"
                f"PREDICTED SOURCE TYPES: {specified_source_types}\n\n"
                f"PREDICTED TIME FILTER: {implied_time_filter}\n\n"
                " --- \n\n"
            ),
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    logger.debug(
        f"Search start for Standard Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    retrieved_docs: list[InferenceSection] = []
    callback_container: list[list[InferenceSection]] = []

    # new db session to avoid concurrency issues
    with get_session_with_current_tenant() as search_db_session:
        for tool_response in search_tool.run(
            query=rewritten_query,
            document_sources=specified_source_types,
            time_filter=implied_time_filter,
            override_kwargs=SearchToolOverrideKwargs(
                force_no_rerank=True,
                alternate_db_session=search_db_session,
                retrieved_sections_callback=callback_container.append,
                skip_query_analysis=True,
            ),
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections

                break

    document_texts_list = []

    for doc_num, retrieved_doc in enumerate(retrieved_docs[:15]):
        if not isinstance(retrieved_doc, (InferenceSection, LlmDoc)):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    logger.debug(
        f"Search end/LLM start for Standard Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Built prompt

    search_prompt = (
        BASIC_SEARCH_PROMPTS[time_budget]
        .replace(
            "---search_query---", branch_query
        )  # use branch query to create answer
        .replace("---base_question---", base_question)
        .replace("---document_text---", document_texts)
    )

    # Run LLM

    # search_answer_json = None
    search_answer_json = invoke_llm_json(
        llm=graph_config.tooling.primary_llm,
        prompt=search_prompt,
        schema=SearchAnswer,
        timeout_override=40,
        max_tokens=1500,
    )

    logger.debug(
        f"LLM/all done for Standard Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=f"ANSWERED {iteration_nr}.{parallelization_nr}\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    # get cited documents
    answer_string = search_answer_json.answer
    claims = search_answer_json.claims or []
    # answer_string = ""
    # claims = []

    (
        citation_numbers,
        answer_string,
        claims,
    ) = extract_document_citations(answer_string, claims)
    cited_documents = {
        citation_number: retrieved_docs[citation_number - 1]
        for citation_number in citation_numbers
    }

    return AnswerUpdate(
        iteration_responses=[
            IterationAnswer(
                tool=DRPath.SEARCH,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=branch_query,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="search",
                node_start_time=node_start_time,
            )
        ],
    )
