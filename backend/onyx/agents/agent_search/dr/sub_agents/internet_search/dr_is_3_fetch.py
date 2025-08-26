from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import SearchAnswer
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetContent,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.providers import (
    get_default_provider,
)
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
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.prompts.dr_prompts import INTERNAL_SEARCH_PROMPTS
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _truncate_search_result_content(content: str, max_chars: int = 10000) -> str:
    """Truncate search result content to a maximum number of characters"""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


def _dummy_inference_section_from_internet_search_result(
    result: InternetContent,
) -> InferenceSection:
    truncated_content = _truncate_search_result_content(result.full_content)
    return InferenceSection(
        center_chunk=InferenceChunk(
            chunk_id=0,
            blurb=result.title,
            content=truncated_content,
            source_links={0: result.link},
            section_continuation=False,
            document_id="INTERNET_SEARCH_DOC_" + result.link,
            source_type=DocumentSource.WEB,
            semantic_identifier=result.link,
            title=result.title,
            boost=1,
            recency_bias=1.0,
            score=1.0,
            hidden=False,
            metadata={},
            match_highlights=[],
            doc_summary=truncated_content,
            chunk_context=truncated_content,
            updated_at=datetime.now(),  # TODO: Add published date
            image_file_id=None,
        ),
        chunks=[],
        combined_content=truncated_content,
    )


def web_fetch(
    state: BranchInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> BranchUpdate:
    """
    LangGraph node to fetch content from URLs and process the results.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    current_step_nr = state.current_step_nr

    assistant_system_prompt = state.assistant_system_prompt
    assistant_task_prompt = state.assistant_task_prompt
    urls_to_open = state.urls_to_open
    search_query = state.branch_question
    if not search_query:
        raise ValueError("search_query is not set")

    if not state.available_tools:
        raise ValueError("available_tools is not set")
    is_tool_info = state.available_tools[state.tools_used[-1]]

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query
    research_type = graph_config.behavior.research_type

    logger.debug(
        f"Web Fetch for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    if graph_config.inputs.persona is None:
        raise ValueError("persona is not set")

    provider = get_default_provider()
    if provider is None:
        raise ValueError("No internet search provider found")

    # Fetch content from URLs
    retrieved_docs: list[InferenceSection] = []
    try:
        retrieved_docs = [
            _dummy_inference_section_from_internet_search_result(result)
            for result in provider.contents(urls_to_open)
        ]
    except Exception as e:
        logger.error(f"Error fetching URLs: {e}")

    if not retrieved_docs:
        logger.warning("No content retrieved from URLs")

    # Process documents and build context
    document_texts_list = []
    for doc_num, retrieved_doc in enumerate(retrieved_docs):
        if not isinstance(retrieved_doc, (InferenceSection, LlmDoc)):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    logger.debug(
        f"Fetch end/LLM start for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Process with LLM based on research type
    if research_type == ResearchType.DEEP:
        search_prompt = INTERNAL_SEARCH_PROMPTS[research_type].build(
            search_query=state.branch_question or "",
            base_question=base_question,
            document_text=document_texts,
        )

        # Run LLM
        search_answer_json = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=create_question_prompt(
                assistant_system_prompt, search_prompt + (assistant_task_prompt or "")
            ),
            schema=SearchAnswer,
            timeout_override=40,
        )

        logger.debug(
            f"LLM/all done for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
        )

        # Get cited documents
        answer_string = search_answer_json.answer
        claims = search_answer_json.claims or []
        reasoning = search_answer_json.reasoning or ""

        (
            citation_numbers,
            answer_string,
            claims,
        ) = extract_document_citations(answer_string, claims)
        cited_documents = {
            citation_number: retrieved_docs[citation_number - 1]
            for citation_number in citation_numbers
        }

    else:
        answer_string = ""
        claims = []
        reasoning = ""
        cited_documents = {
            doc_num + 1: retrieved_doc
            for doc_num, retrieved_doc in enumerate(retrieved_docs[:15])
        }

    write_custom_event(
        current_step_nr,
        SearchToolDelta(
            queries=[],
            documents=convert_inference_sections_to_search_docs(
                retrieved_docs, is_internet=True
            ),
        ),
        writer,
    )

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=is_tool_info.llm_path,
                tool_id=is_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=search_query,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
                reasoning=reasoning,
                additional_data=None,
                urls_to_open=urls_to_open,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="fetching",
                node_start_time=node_start_time,
            )
        ],
    )
