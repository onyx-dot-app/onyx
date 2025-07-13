from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.access.access import get_acl_for_user
from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.utils import get_cited_document_numbers
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import get_answer_from_llm
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import relevance_from_docs
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.prompts.dr_prompts import BASIC_SEARCH_PROMPT
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.utils.logger import setup_logger

logger = setup_logger()


def search(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> AnswerUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    iteration_nr = state.iteration_nr

    node_start_time = datetime.now()

    search_query = state.query_list[0]  # TODO: fix this
    base_question = config["metadata"]["config"].inputs.prompt_builder.raw_user_query

    node_start_time = datetime.now()
    query_to_retrieve = search_query
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    search_tool = graph_config.tooling.search_tool

    user = (
        graph_config.tooling.search_tool.user
        if graph_config.tooling.search_tool
        else None
    )

    if not user:
        raise ValueError("User is not set")

    retrieved_docs: list[InferenceSection] = []

    if search_tool is None:
        raise ValueError("search_tool must be provided for agentic search")

    callback_container: list[list[InferenceSection]] = []

    # new db session to avoid concurrency issues
    with get_session_with_current_tenant() as search_db_session:

        list(get_acl_for_user(user, search_db_session))

        for tool_response in search_tool.run(
            query=query_to_retrieve,
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

    # stream_write_step_answer_explicit(writer, step_nr=1, answer=full_answer)

    relevance_from_docs(retrieved_docs)

    """
    # keep for later use
    for tool_response in yield_search_responses(
        query=query_to_retrieve,
        get_retrieved_sections=lambda: retrieved_docs,
        get_final_context_sections=lambda: retrieved_docs,
        search_query_info=SearchQueryInfo(
            predicted_search=SearchType.KEYWORD,
            # acl here is empty, because the searach alrady happened and
            # we are streaming out the results.
            final_filters=IndexFilters(access_control_list=user_acl),
            recency_bias_multiplier=1.0,
        ),
        get_section_relevance=lambda: relevance_list,
        search_tool=search_tool,
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

    """
    document_texts_list = []

    for doc_num, retrieved_doc in enumerate(retrieved_docs):
        if not isinstance(retrieved_doc, (InferenceSection, LlmDoc)):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    # Built prompt

    search_prompt = (
        BASIC_SEARCH_PROMPT.replace("---search_query---", search_query)
        .replace("---base_question---", base_question)
        .replace("---document_text---", document_texts)
    )

    # Run LLM

    search_answer = get_answer_from_llm(
        graph_config.tooling.primary_llm,
        search_prompt,
        timeout=40,
        timeout_override=40,
        max_tokens=1500,
        stream=False,
        json_string_flag=False,
    )

    logger.debug(f"Conducting a standard search for: {search_query}")
    logger.debug(f"Search answer: {search_answer}")

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=f"\n\nSUB-QUESTION (SEARCH): {search_query}\n\n-> answered!\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    # handle citations

    citation_numbers = get_cited_document_numbers(search_answer)
    citation_number_replacement_dict = {
        original_index: start_1_based_index + 1
        for start_1_based_index, original_index in enumerate(citation_numbers)
    }

    cited_documents: list[InferenceSection] = []

    for citation_number in citation_numbers:
        cited_documents.append(retrieved_docs[citation_number - 1])

    # change citations from search answer
    for original_index, replacement_index in citation_number_replacement_dict.items():
        search_answer = search_answer.replace(
            f"[{original_index}]", f"[{replacement_index}]"
        )

    return AnswerUpdate(
        answers=[search_answer],
        iteration_responses=[
            {
                iteration_nr: {
                    0: {"Q": search_query, "A": search_answer, "C": cited_documents}
                }
            }
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="kg search",
                node_start_time=node_start_time,
            )
        ],
    )
