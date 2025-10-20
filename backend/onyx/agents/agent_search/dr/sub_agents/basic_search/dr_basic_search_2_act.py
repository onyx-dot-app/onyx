import re
from datetime import datetime
from typing import cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import BaseSearchProcessingResponse
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import SearchAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.chat.models import LlmDoc
from onyx.configs.agent_configs import TF_DR_TIMEOUT_LONG
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.context.search.models import InferenceSection
from onyx.db.connector import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.prompts.dr_prompts import BASE_SEARCH_PROCESSING_PROMPT
from onyx.prompts.dr_prompts import INTERNAL_SEARCH_PROMPTS
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def basic_search(
    state: BranchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> BranchUpdate:
    """
    LangGraph node to perform a standard search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    current_step_nr = state.current_step_nr
    assistant_system_prompt = state.assistant_system_prompt
    assistant_task_prompt = state.assistant_task_prompt

    branch_query = state.branch_question
    if not branch_query:
        raise ValueError("branch_query is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query
    research_type = graph_config.behavior.research_type

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    elif len(state.tools_used) == 0:
        raise ValueError("tools_used is empty")

    search_tool_info = state.available_tools[state.tools_used[-1]]
    search_tool = cast(SearchTool, search_tool_info.tool_object)
    force_use_tool = graph_config.tooling.force_use_tool

    # sanity check
    if search_tool != graph_config.tooling.search_tool:
        raise ValueError("search_tool does not match the configured search tool")

    # rewrite query and identify source types
    active_source_types_str = ", ".join(
        [source.value for source in state.active_source_types or []]
    )

    base_search_processing_prompt = BASE_SEARCH_PROCESSING_PROMPT.build(
        active_source_types_str=active_source_types_str,
        branch_query=branch_query,
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    try:
        search_processing = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=create_question_prompt(
                assistant_system_prompt, base_search_processing_prompt
            ),
            schema=BaseSearchProcessingResponse,
            timeout_override=TF_DR_TIMEOUT_SHORT,
            # max_tokens=100,
        )
    except Exception as e:
        logger.error(f"Could not process query: {e}")
        raise e

    rewritten_query = search_processing.rewritten_query

    # give back the query so we can render it in the UI
    write_custom_event(
        current_step_nr,
        SearchToolDelta(
            queries=[rewritten_query],
            documents=[],
        ),
        writer,
    )

    implied_start_date = search_processing.time_filter

    # Validate time_filter format if it exists
    implied_time_filter = None
    if implied_start_date:

        # Check if time_filter is in YYYY-MM-DD format
        date_pattern = r"^\d{4}-\d{2}-\d{2}$"
        if re.match(date_pattern, implied_start_date):
            implied_time_filter = datetime.strptime(implied_start_date, "%Y-%m-%d")

    specified_source_types: list[DocumentSource] | None = [
        DocumentSource(source_type)
        for source_type in search_processing.specified_source_types
    ]

    if specified_source_types is not None and len(specified_source_types) == 0:
        specified_source_types = None

    logger.debug(
        f"Search start for Standard Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    retrieved_docs: list[InferenceSection] = []
    callback_container: list[list[InferenceSection]] = []

    user_file_ids: list[UUID] | None = None
    project_id: int | None = None
    if force_use_tool.override_kwargs and isinstance(
        force_use_tool.override_kwargs, SearchToolOverrideKwargs
    ):
        override_kwargs = force_use_tool.override_kwargs
        user_file_ids = override_kwargs.user_file_ids
        project_id = override_kwargs.project_id

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
                original_query=rewritten_query,
                user_file_ids=user_file_ids,
                project_id=project_id,
            ),
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections

                break

    # render the retrieved docs in the UI
    write_custom_event(
        current_step_nr,
        SearchToolDelta(
            queries=[],
            documents=convert_inference_sections_to_search_docs(
                retrieved_docs, is_internet=False
            ),
        ),
        writer,
    )

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

    if research_type == ResearchType.DEEP:
        search_prompt = INTERNAL_SEARCH_PROMPTS[research_type].build(
            search_query=branch_query,
            base_question=base_question,
            document_text=document_texts,
        )

        # Run LLM

        # search_answer_json = None
        search_answer_json = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=create_question_prompt(
                assistant_system_prompt, search_prompt + (assistant_task_prompt or "")
            ),
            schema=SearchAnswer,
            timeout_override=TF_DR_TIMEOUT_LONG,
            # max_tokens=1500,
        )

        logger.debug(
            f"LLM/all done for Standard Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
        )

        # get cited documents
        answer_string = search_answer_json.answer
        claims = search_answer_json.claims or []
        reasoning = search_answer_json.reasoning
        # answer_string = ""
        # claims = []

        (
            citation_numbers,
            answer_string,
            claims,
        ) = extract_document_citations(answer_string, claims)

        if citation_numbers and (
            (max(citation_numbers) > len(retrieved_docs)) or min(citation_numbers) < 1
        ):
            raise ValueError("Citation numbers are out of range for retrieved docs.")

        cited_documents = {
            citation_number: retrieved_docs[citation_number - 1]
            for citation_number in citation_numbers
        }

    else:
        answer_string = ""
        claims = []
        cited_documents = {
            doc_num + 1: retrieved_doc
            for doc_num, retrieved_doc in enumerate(retrieved_docs[:15])
        }
        reasoning = ""

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=search_tool_info.llm_path,
                tool_id=search_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=branch_query,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
                reasoning=reasoning,
                additional_data=None,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="basic_search",
                node_name="searching",
                node_start_time=node_start_time,
            )
        ],
    )
