import re
from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search.main.operations import logger
from onyx.agents.agent_search.deep_search.main.states import (
    EntityTermExtractionUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.models import EntityExtractionResult
from onyx.agents.agent_search.shared_graph_utils.models import (
    EntityRelationshipTermExtraction,
)
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.constants import NUM_EXPLORATORY_DOCS
from onyx.prompts.agent_search import (
    ENTITY_TERM_EXTRACTION_PROMPT,
)


def extract_entities_terms(
    state: MainState, config: RunnableConfig
) -> EntityTermExtractionUpdate:
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    if not graph_config.behavior.allow_refinement:
        return EntityTermExtractionUpdate(
            entity_relation_term_extractions=EntityRelationshipTermExtraction(
                entities=[],
                relationships=[],
                terms=[],
            ),
            log_messages=[
                get_langgraph_node_log_string(
                    graph_component="main",
                    node_name="extract entities terms",
                    node_start_time=node_start_time,
                    result="Refinement is not allowed",
                )
            ],
        )

    # first four lines duplicates from generate_initial_answer
    question = graph_config.inputs.search_request.query
    initial_search_docs = state.exploratory_search_results[:NUM_EXPLORATORY_DOCS]

    # start with the entity/term/extraction
    doc_context = format_docs(initial_search_docs)

    doc_context = trim_prompt_piece(
        graph_config.tooling.fast_llm.config,
        doc_context,
        ENTITY_TERM_EXTRACTION_PROMPT + question,
    )
    msg = [
        HumanMessage(
            content=ENTITY_TERM_EXTRACTION_PROMPT.format(
                question=question, context=doc_context
            ),
        )
    ]
    fast_llm = graph_config.tooling.fast_llm
    # Grader
    llm_response = fast_llm.invoke(
        prompt=msg,
    )

    cleaned_response = re.sub(r"```json\n|\n```", "", str(llm_response.content))

    try:
        entity_extraction_result = EntityExtractionResult.model_validate_json(
            cleaned_response
        )
    except ValueError:
        logger.error("Failed to parse LLM response as JSON in Entity-Term Extraction")
        entity_extraction_result = EntityExtractionResult(
            retrieved_entities_relationships=EntityRelationshipTermExtraction(
                entities=[],
                relationships=[],
                terms=[],
            ),
        )

    return EntityTermExtractionUpdate(
        entity_relation_term_extractions=entity_extraction_result.retrieved_entities_relationships,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="extract entities terms",
                node_start_time=node_start_time,
            )
        ],
    )
