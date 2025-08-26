from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.kb_search.graph_utils import get_near_empty_step_results
from onyx.agents.agent_search.kb_search.ops import research
from onyx.agents.agent_search.kb_search.states import ConsolidatedResearchUpdate
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.calculations import (
    get_answer_generation_documents,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.kg_configs import KG_FILTERED_SEARCH_TIMEOUT
from onyx.configs.kg_configs import KG_RESEARCH_NUM_RETRIEVED_DOCS
from onyx.context.search.models import InferenceSection
from onyx.prompts.kg_prompts import KG_SEARCH_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout


logger = setup_logger()


def filtered_search(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ConsolidatedResearchUpdate:
    """
    LangGraph node to do a filtered search.
    """
    _KG_STEP_NR = 4

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    search_tool = graph_config.tooling.search_tool
    question = state.question

    if not search_tool:
        raise ValueError("search_tool is not provided")

    if not state.vespa_filter_results:
        raise ValueError("vespa_filter_results is not provided")
    raw_kg_entity_filters = list(
        set((state.vespa_filter_results.global_entity_filters))
    )

    kg_entity_filters = []
    for raw_kg_entity_filter in raw_kg_entity_filters:
        if "::" not in raw_kg_entity_filter:
            raw_kg_entity_filter += "::*"
        kg_entity_filters.append(raw_kg_entity_filter)

    kg_relationship_filters = state.vespa_filter_results.global_relationship_filters

    logger.debug("Starting filtered search")
    logger.debug(f"kg_entity_filters: {kg_entity_filters}")
    logger.debug(f"kg_relationship_filters: {kg_relationship_filters}")

    retrieved_docs = cast(
        list[InferenceSection],
        research(
            question=question,
            kg_entities=kg_entity_filters,
            kg_relationships=kg_relationship_filters,
            kg_sources=None,
            search_tool=search_tool,
            inference_sections_only=True,
        ),
    )

    source_link_dict = {
        num + 1: doc.center_chunk.source_links[0]
        for num, doc in enumerate(retrieved_docs)
        if doc.center_chunk.source_links
    }

    answer_generation_documents = get_answer_generation_documents(
        relevant_docs=retrieved_docs,
        context_documents=retrieved_docs,
        original_question_docs=retrieved_docs,
        max_docs=KG_RESEARCH_NUM_RETRIEVED_DOCS,
    )

    document_texts_list = []

    for doc_num, retrieved_doc in enumerate(
        answer_generation_documents.context_documents
    ):
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    # Built prompt

    datetime.now().strftime("%A, %Y-%m-%d")

    kg_object_source_research_prompt = KG_SEARCH_PROMPT.format(
        question=question,
        document_text=document_texts,
    )

    # Run LLM

    msg = [
        HumanMessage(
            content=trim_prompt_piece(
                config=graph_config.tooling.primary_llm.config,
                prompt_piece=kg_object_source_research_prompt,
                reserved_str="",
            ),
        )
    ]
    primary_llm = graph_config.tooling.primary_llm
    llm = primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            KG_FILTERED_SEARCH_TIMEOUT,
            llm.invoke,
            prompt=msg,
            timeout_override=30,
            max_tokens=300,
        )

        filtered_search_answer = str(llm_response.content).replace("```json\n", "")

        # TODO: make sure the citations look correct. Currently, they do not.
        for source_link_num, source_link in source_link_dict.items():
            if f"[{source_link_num}]" in filtered_search_answer:
                filtered_search_answer = filtered_search_answer.replace(
                    f"[{source_link_num}]", f"[{source_link_num}]({source_link})"
                )

    except Exception as e:
        raise ValueError(f"Error in filtered_search: {e}")

    step_answer = "Filtered search is complete."

    return ConsolidatedResearchUpdate(
        consolidated_research_object_results_str=filtered_search_answer,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="filtered search",
                node_start_time=node_start_time,
            )
        ],
        step_results=[
            get_near_empty_step_results(
                step_number=_KG_STEP_NR,
                step_answer=step_answer,
                verified_reranked_documents=retrieved_docs,
            )
        ],
    )
