import copy
from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.kb_search.ops import research
from onyx.agents.agent_search.kb_search.states import KGSourceDivisionType
from onyx.agents.agent_search.kb_search.states import ResearchObjectInput
from onyx.agents.agent_search.kb_search.states import ResearchObjectUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.chat.models import LlmDoc
from onyx.configs.kg_configs import KG_MAX_SEARCH_DOCUMENTS
from onyx.configs.kg_configs import KG_OBJECT_SOURCE_RESEARCH_TIMEOUT
from onyx.context.search.models import InferenceSection
from onyx.kg.utils.formatting_utils import split_entity_id
from onyx.prompts.kg_prompts import KG_OBJECT_SOURCE_RESEARCH_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def process_individual_deep_search(
    state: ResearchObjectInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> ResearchObjectUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    search_tool = graph_config.tooling.search_tool
    question = state.broken_down_question
    segment_type = state.segment_type

    object = state.entity.replace("::", ":: ").lower()

    if not search_tool:
        raise ValueError("search_tool is not provided")

    state.research_nr

    if segment_type == KGSourceDivisionType.ENTITY.value:

        object_id = split_entity_id(object)[1].strip()
        extended_question = f"{question} in regards to {object}"
        source_filters = state.source_entity_filters

        # TODO: this does not really occur in V1. But needs to be changed for V2
        raw_kg_entity_filters = copy.deepcopy(
            list(
                set((state.vespa_filter_results.global_entity_filters + [state.entity]))
            )
        )

        kg_entity_filters = []
        for raw_kg_entity_filter in raw_kg_entity_filters:
            if "::" not in raw_kg_entity_filter:
                raw_kg_entity_filter += "::*"
            kg_entity_filters.append(raw_kg_entity_filter)

        kg_relationship_filters = copy.deepcopy(
            state.vespa_filter_results.global_relationship_filters
        )

        logger.debug("Research for object: " + object)
        logger.debug(f"kg_entity_filters: {kg_entity_filters}")
        logger.debug(f"kg_relationship_filters: {kg_relationship_filters}")

    else:
        # if we came through the entity view route, in KG V1 the state entity
        # is the document to search for. No need to set other filters then.
        object_id = state.entity  # source doc in this case
        extended_question = f"{question}"
        source_filters = [object_id]

        kg_entity_filters = None
        kg_relationship_filters = None

    if source_filters and (len(source_filters) > KG_MAX_SEARCH_DOCUMENTS):
        logger.debug(
            f"Too many sources ({len(source_filters)}), setting to None and effectively filtered search"
        )
        source_filters = None

    retrieved_docs = research(
        question=extended_question,
        kg_entities=kg_entity_filters,
        kg_relationships=kg_relationship_filters,
        kg_sources=source_filters,
        search_tool=search_tool,
    )

    document_texts_list = []

    for doc_num, retrieved_doc in enumerate(retrieved_docs):
        if not isinstance(retrieved_doc, (InferenceSection, LlmDoc)):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    # Built prompt

    kg_object_source_research_prompt = KG_OBJECT_SOURCE_RESEARCH_PROMPT.format(
        question=extended_question,
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
    # Grader
    try:
        llm_response = run_with_timeout(
            KG_OBJECT_SOURCE_RESEARCH_TIMEOUT,
            primary_llm.invoke,
            prompt=msg,
            timeout_override=KG_OBJECT_SOURCE_RESEARCH_TIMEOUT,
            max_tokens=300,
        )

        object_research_results = str(llm_response.content).replace("```json\n", "")

    except Exception as e:
        raise ValueError(f"Error in research_object_source: {e}")

    logger.debug("DivCon Step A2 - Object Source Research - completed for an object")

    return ResearchObjectUpdate(
        research_object_results=[
            {
                "object": object.replace("::", ":: ").capitalize(),
                "results": object_research_results,
            }
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="process individual deep search",
                node_start_time=node_start_time,
            )
        ],
        step_results=[],
    )
