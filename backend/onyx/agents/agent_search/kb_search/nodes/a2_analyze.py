from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.graph_utils import (
    create_minimal_connected_query_graph,
)
from onyx.agents.agent_search.kb_search.graph_utils import get_near_empty_step_results
from onyx.agents.agent_search.kb_search.models import KGAnswerApproach
from onyx.agents.agent_search.kb_search.states import AnalysisUpdate
from onyx.agents.agent_search.kb_search.states import KGAnswerFormat
from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import KGRelationshipDetection
from onyx.agents.agent_search.kb_search.states import KGSearchType
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import YesNoEnum
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.kg_configs import KG_STRATEGY_GENERATION_TIMEOUT
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entities import get_document_id_for_entity
from onyx.kg.clustering.normalizations import normalize_entities
from onyx.kg.clustering.normalizations import normalize_relationships
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.prompts.kg_prompts import STRATEGY_GENERATION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def _articulate_normalizations(
    entity_normalization_map: dict[str, str],
    relationship_normalization_map: dict[str, str],
) -> str:

    remark_list: list[str] = []

    if entity_normalization_map:
        remark_list.append("\n Entities:")
        for extracted_entity, normalized_entity in entity_normalization_map.items():
            remark_list.append(f"  - {extracted_entity} -> {normalized_entity}")

    if relationship_normalization_map:
        remark_list.append(" \n Relationships:")
        for (
            extracted_relationship,
            normalized_relationship,
        ) in relationship_normalization_map.items():
            remark_list.append(
                f"  - {extracted_relationship} -> {normalized_relationship}"
            )

    return " \n ".join(remark_list)


def _get_fully_connected_entities(
    entities: list[str], relationships: list[str]
) -> list[str]:
    """
    Analyze the connectedness of the entities and relationships.
    """
    # Build a dictionary to track connections for each entity
    entity_connections: dict[str, set[str]] = {entity: set() for entity in entities}

    # Parse relationships to build connection graph
    for relationship in relationships:
        # Split relationship into parts. Test for proper formatting just in case.
        # Should never be an error though at this point.
        parts = split_relationship_id(relationship)
        if len(parts) != 3:
            raise ValueError(f"Invalid relationship: {relationship}")

        entity1 = parts[0]
        entity2 = parts[2]

        # Add bidirectional connections
        if entity1 in entity_connections:
            entity_connections[entity1].add(entity2)
        if entity2 in entity_connections:
            entity_connections[entity2].add(entity1)

    # Find entities connected to all others
    fully_connected_entities = []
    all_entities = set(entities)

    for entity, connections in entity_connections.items():
        # Check if this entity is connected to all other entities
        if connections == all_entities - {entity}:
            fully_connected_entities.append(entity)

    return fully_connected_entities


def _check_for_single_doc(
    normalized_entities: list[str],
    raw_entities: list[str],
    normalized_relationship_strings: list[str],
    raw_relationships: list[str],
    normalized_time_filter: str | None,
) -> str | None:
    """
    Check if the query is for a single document, like 'Summarize ticket ENG-2243K'.
    None is returned if the query is not for a single document.
    """
    if (
        len(normalized_entities) == 1
        and len(raw_entities) == 1
        and len(normalized_relationship_strings) == 0
        and len(raw_relationships) == 0
        and normalized_time_filter is None
    ):
        with get_session_with_current_tenant() as db_session:
            single_doc_id = get_document_id_for_entity(
                db_session, normalized_entities[0]
            )
    else:
        single_doc_id = None
    return single_doc_id


def analyze(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> AnalysisUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    _KG_STEP_NR = 2

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.question
    entities = (
        state.extracted_entities_no_attributes
    )  # attribute knowledge is not required for this step
    relationships = state.extracted_relationships
    time_filter = state.time_filter

    ## STEP 2 - stream out goals

    # Continue with node

    normalized_entities = normalize_entities(
        entities,
        state.extracted_entities_w_attributes,
        allowed_docs_temp_view_name=state.kg_doc_temp_view_name,
    )

    normalized_relationships = normalize_relationships(
        relationships, normalized_entities.entity_normalization_map
    )
    normalized_time_filter = time_filter

    # If single-doc inquiry, send to single-doc processing directly

    single_doc_id = _check_for_single_doc(
        normalized_entities=normalized_entities.entities,
        raw_entities=entities,
        normalized_relationship_strings=normalized_relationships.relationships,
        raw_relationships=relationships,
        normalized_time_filter=normalized_time_filter,
    )

    # Expand the entities and relationships to make sure that entities are connected

    graph_expansion = create_minimal_connected_query_graph(
        normalized_entities.entities,
        normalized_relationships.relationships,
        max_depth=2,
    )

    query_graph_entities = graph_expansion.entities
    query_graph_relationships = graph_expansion.relationships

    # Evaluate whether a search needs to be done after identifying all entities and relationships

    strategy_generation_prompt = (
        STRATEGY_GENERATION_PROMPT.replace(
            "---entities---", "\n".join(query_graph_entities)
        )
        .replace("---relationships---", "\n".join(query_graph_relationships))
        .replace("---possible_entities---", state.entities_types_str)
        .replace("---possible_relationships---", state.relationship_types_str)
        .replace("---question---", question)
    )

    msg = [
        HumanMessage(
            content=strategy_generation_prompt,
        )
    ]
    primary_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            KG_STRATEGY_GENERATION_TIMEOUT,
            # fast_llm.invoke,
            primary_llm.invoke,
            prompt=msg,
            timeout_override=5,
            max_tokens=100,
        )

        cleaned_response = (
            str(llm_response.content)
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]

        try:
            approach_extraction_result = KGAnswerApproach.model_validate_json(
                cleaned_response
            )
            search_type = approach_extraction_result.search_type
            search_strategy = approach_extraction_result.search_strategy
            relationship_detection = (
                approach_extraction_result.relationship_detection.value
            )
            output_format = approach_extraction_result.format
            broken_down_question = approach_extraction_result.broken_down_question
            divide_and_conquer = approach_extraction_result.divide_and_conquer
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            search_type = KGSearchType.SEARCH
            search_strategy = KGAnswerStrategy.DEEP
            relationship_detection = KGRelationshipDetection.RELATIONSHIPS.value
            output_format = KGAnswerFormat.TEXT
            broken_down_question = None
            divide_and_conquer = YesNoEnum.NO
        if search_strategy is None or output_format is None:
            raise ValueError(f"Invalid strategy: {cleaned_response}")

    except Exception as e:
        logger.error(f"Error in strategy generation: {e}")
        raise e

    # Stream out relevant results

    if single_doc_id:
        search_strategy = (
            KGAnswerStrategy.DEEP
        )  # if a single doc is identified, we will want to look at the details.

    step_answer = f"Strategy and format have been extracted from query. Strategy: {search_strategy.value}, \
Format: {output_format.value}, Broken down question: {broken_down_question}"

    extraction_detected_relationships = len(query_graph_relationships) > 0
    if extraction_detected_relationships:
        query_type = KGRelationshipDetection.RELATIONSHIPS.value

        if extraction_detected_relationships:
            logger.warning(
                "Fyi - Extraction detected relationships: "
                f"{extraction_detected_relationships}, "
                f"but relationship detection: {relationship_detection}"
            )
    else:
        query_type = KGRelationshipDetection.NO_RELATIONSHIPS.value

    # End node

    return AnalysisUpdate(
        normalized_core_entities=normalized_entities.entities,
        normalized_core_relationships=normalized_relationships.relationships,
        entity_normalization_map=normalized_entities.entity_normalization_map,
        relationship_normalization_map=normalized_relationships.relationship_normalization_map,
        query_graph_entities_no_attributes=query_graph_entities,
        query_graph_entities_w_attributes=normalized_entities.entities_w_attributes,
        query_graph_relationships=query_graph_relationships,
        normalized_terms=[],  # TODO: remove fully later
        normalized_time_filter=normalized_time_filter,
        strategy=search_strategy,
        broken_down_question=broken_down_question,
        output_format=output_format,
        divide_and_conquer=divide_and_conquer,
        single_doc_id=single_doc_id,
        search_type=search_type,
        query_type=query_type,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="analyze",
                node_start_time=node_start_time,
            )
        ],
        step_results=[
            get_near_empty_step_results(
                step_number=_KG_STEP_NR,
                step_answer=step_answer,
                verified_reranked_documents=[],
            )
        ],
        remarks=[
            _articulate_normalizations(
                entity_normalization_map=normalized_entities.entity_normalization_map,
                relationship_normalization_map=normalized_relationships.relationship_normalization_map,
            )
        ],
    )
