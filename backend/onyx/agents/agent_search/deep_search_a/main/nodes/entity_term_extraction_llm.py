import json
import re
from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_message_runs
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import (
    EntityTermExtractionUpdate,
)
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.models import Entity
from onyx.agents.agent_search.shared_graph_utils.models import (
    EntityRelationshipTermExtraction,
)
from onyx.agents.agent_search.shared_graph_utils.models import Relationship
from onyx.agents.agent_search.shared_graph_utils.models import Term
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import ENTITY_TERM_PROMPT
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs


def entity_term_extraction_llm(
    state: MainState, config: RunnableConfig
) -> EntityTermExtractionUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE ENTITIES & TERMS---")

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    if not agent_a_config.allow_refinement:
        return EntityTermExtractionUpdate(
            entity_retlation_term_extractions=EntityRelationshipTermExtraction(
                entities=[],
                relationships=[],
                terms=[],
            )
        )

    # first four lines duplicates from generate_initial_answer
    question = agent_a_config.search_request.query
    sub_question_docs = state.documents
    all_original_question_documents = state.all_original_question_documents
    relevant_docs = dedup_inference_sections(
        sub_question_docs, all_original_question_documents
    )

    # start with the entity/term/extraction
    doc_context = format_docs(relevant_docs)

    doc_context = trim_prompt_piece(
        agent_a_config.fast_llm.config, doc_context, ENTITY_TERM_PROMPT + question
    )
    msg = [
        HumanMessage(
            content=ENTITY_TERM_PROMPT.format(question=question, context=doc_context),
        )
    ]
    fast_llm = agent_a_config.fast_llm
    # Grader
    llm_response_list = list(
        fast_llm.stream(
            prompt=msg,
        )
    )
    llm_response = merge_message_runs(llm_response_list, chunk_separator="")[0].content

    cleaned_response = re.sub(r"```json\n|\n```", "", llm_response)
    parsed_response = json.loads(cleaned_response)

    entities = []
    relationships = []
    terms = []
    for entity in parsed_response.get("retrieved_entities_relationships", {}).get(
        "entities", {}
    ):
        entity_name = entity.get("entity_name", "")
        entity_type = entity.get("entity_type", "")
        entities.append(Entity(entity_name=entity_name, entity_type=entity_type))

    for relationship in parsed_response.get("retrieved_entities_relationships", {}).get(
        "relationships", {}
    ):
        relationship_name = relationship.get("relationship_name", "")
        relationship_type = relationship.get("relationship_type", "")
        relationship_entities = relationship.get("relationship_entities", [])
        relationships.append(
            Relationship(
                relationship_name=relationship_name,
                relationship_type=relationship_type,
                relationship_entities=relationship_entities,
            )
        )

    for term in parsed_response.get("retrieved_entities_relationships", {}).get(
        "terms", {}
    ):
        term_name = term.get("term_name", "")
        term_type = term.get("term_type", "")
        term_similar_to = term.get("term_similar_to", [])
        terms.append(
            Term(
                term_name=term_name,
                term_type=term_type,
                term_similar_to=term_similar_to,
            )
        )

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------ENTITY TERM EXTRACTION END---"
    )

    return EntityTermExtractionUpdate(
        entity_retlation_term_extractions=EntityRelationshipTermExtraction(
            entities=entities,
            relationships=relationships,
            terms=terms,
        ),
        log_messages=[
            f"{now_start} -- Entity Term Extraction - Time taken: {now_end - now_start}"
        ],
    )
