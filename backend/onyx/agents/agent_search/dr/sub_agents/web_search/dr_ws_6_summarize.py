from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import SearchAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.sub_agents.web_search.states import SummarizeInput
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.context.search.models import InferenceSection
from onyx.prompts.dr_prompts import INTERNAL_SEARCH_PROMPTS
from onyx.utils.logger import setup_logger


logger = setup_logger()


def is_summarize(
        state: SummarizeInput,
        config: RunnableConfig,
        writer: StreamWriter = lambda _: None,
) -> BranchUpdate:
    """
    LangGraph node to perform a internet search as part of the DR process.
    """

    node_start_time = datetime.now()

    # build branch iterations from fetch inputs
    url_to_raw_document: dict[str, InferenceSection] = {}
    for raw_document in state.raw_documents:
        # NOTE: raw_document.center_chunk.semantic_identifier is the URL link
        url_to_raw_document[raw_document.center_chunk.semantic_identifier] = (
            raw_document
        )
    urls = state.branch_questions_to_urls[state.branch_question]
    current_iteration = state.iteration_nr
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    research_type = graph_config.behavior.research_type
    if not state.available_tools:
        raise ValueError("available_tools is not set")
    is_tool_info = state.available_tools[state.tools_used[-1]]

    # --- Start of Fix ---

    # Safely build the list of documents, skipping any URL that was not fetched.
    cited_raw_documents: list[InferenceSection] = []
    for url in urls:
        if url in url_to_raw_document:
            cited_raw_documents.append(url_to_raw_document[url])
        else:
            # This logs the skipped URL, which resolves the KeyError
            logger.warning(
                f"Skipping document citation for unfetched/blocked URL: {url}. "
                "Document was not found in url_to_raw_document map."
            )

    if not cited_raw_documents:
        # If no documents were successfully fetched, return an empty answer
        return BranchUpdate(
            branch_iteration_responses=[
                IterationAnswer(
                    tool=is_tool_info.llm_path,
                    tool_id=is_tool_info.tool_id,
                    iteration_nr=current_iteration,
                    parallelization_nr=0,
                    question=state.branch_question,
                    answer="No relevant content could be retrieved from the internet.",
                    claims=[],
                    cited_documents={},
                    reasoning="All cited URLs were blocked or failed to load.",
                    additional_data=None,
                )
            ],
            log_messages=[
                get_langgraph_node_log_string(
                    graph_component="internet_search",
                    node_name="summarizing (no content)",
                    node_start_time=node_start_time,
                )
            ],
        )

    # --- End of Fix ---

    if research_type == ResearchType.DEEP:
        # The list comprehension causing the error has been replaced by the safe loop above
        # cited_raw_documents = [url_to_raw_document[url] for url in urls] # <-- Removed

        document_texts = _create_document_texts(cited_raw_documents)
        search_prompt = INTERNAL_SEARCH_PROMPTS[research_type].build(
            search_query=state.branch_question,
            base_question=graph_config.inputs.prompt_builder.raw_user_query,
            document_text=document_texts,
        )
        assistant_system_prompt = state.assistant_system_prompt
        assistant_task_prompt = state.assistant_task_prompt
        search_answer_json = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=create_question_prompt(
                assistant_system_prompt, search_prompt + (assistant_task_prompt or "")
            ),
            schema=SearchAnswer,
            timeout_override=TF_DR_TIMEOUT_SHORT,
        )
        answer_string = search_answer_json.answer
        claims = search_answer_json.claims or []
        reasoning = search_answer_json.reasoning or ""
        (
            citation_numbers,
            answer_string,
            claims,
        ) = extract_document_citations(answer_string, claims)

        # NOTE: This indexing is now safe because cited_raw_documents only contains fetched docs
        cited_documents = {
            citation_number: cited_raw_documents[citation_number - 1]
            for citation_number in citation_numbers
        }

    else:
        answer_string = ""
        reasoning = ""
        claims = []

        # The list comprehension causing the error has been replaced by the safe loop above
        # cited_raw_documents = [url_to_raw_document[url] for url in urls] # <-- Removed

        # NOTE: cited_raw_documents is now the safely filtered list
        cited_documents = {
            doc_num + 1: retrieved_doc
            for doc_num, retrieved_doc in enumerate(cited_raw_documents)
        }

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=is_tool_info.llm_path,
                tool_id=is_tool_info.tool_id,
                iteration_nr=current_iteration,
                parallelization_nr=0,
                question=state.branch_question,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
                reasoning=reasoning,
                additional_data=None,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="summarizing",
                node_start_time=node_start_time,
            )
        ],
    )


def _create_document_texts(raw_documents: list[InferenceSection]) -> str:
    document_texts_list = []
    for doc_num, retrieved_doc in enumerate(raw_documents):
        if not isinstance(retrieved_doc, InferenceSection):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)
    return "\n\n".join(document_texts_list)