import copy
from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.ops import research
from onyx.agents.agent_search.kb_search.states import ResearchObjectInput
from onyx.agents.agent_search.kb_search.states import ResearchObjectUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
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
    source_division = state.source_division

    if not search_tool:
        raise ValueError("search_tool is not provided")

    object = state.entity.replace(":", ": ").lower()

    if source_division:
        extended_question = question
    else:
        extended_question = f"{question} in regards to {object}"

    kg_entity_filters = copy.deepcopy(
        state.vespa_filter_results.entity_filters + [state.entity]
    )
    kg_relationship_filters = copy.deepcopy(
        state.vespa_filter_results.relationship_filters
    )

    logger.info("Research for object: " + object)
    logger.info(f"kg_entity_filters: {kg_entity_filters}")
    logger.info(f"kg_relationship_filters: {kg_relationship_filters}")

    # Add random wait between 1-3 seconds
    # time.sleep(random.uniform(0, 3))

    retrieved_docs = research(
        question=extended_question,
        kg_entities=kg_entity_filters,
        kg_relationships=kg_relationship_filters,
        search_tool=search_tool,
    )

    document_texts_list = []
    for doc_num, doc in enumerate(retrieved_docs):
        chunk_text = "Document " + str(doc_num + 1) + ":\n" + doc.content
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    # Built prompt

    datetime.now().strftime("%A, %Y-%m-%d")

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
    # fast_llm = graph_config.tooling.fast_llm
    primary_llm = graph_config.tooling.primary_llm
    llm = primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            30,
            llm.invoke,
            prompt=msg,
            timeout_override=30,
            max_tokens=300,
        )

        object_research_results = str(llm_response.content).replace("```json\n", "")

    except Exception as e:
        raise ValueError(f"Error in research_object_source: {e}")

    logger.debug("DivCon Step A2 - Object Source Research - completed for an object")

    return ResearchObjectUpdate(
        research_object_results=[
            {
                "object": object.replace(":", ": ").capitalize(),
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
    )
