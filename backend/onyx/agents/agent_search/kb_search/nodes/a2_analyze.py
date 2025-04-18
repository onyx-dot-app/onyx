from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.graph_utils import (
    create_minimal_connected_query_graph,
)
from onyx.agents.agent_search.kb_search.models import KGAnswerApproach
from onyx.agents.agent_search.kb_search.states import AnalysisUpdate
from onyx.agents.agent_search.kb_search.states import KGAnswerFormat
from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import YesNoEnum
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.kg.clustering.normalizations import normalize_entities
from onyx.kg.clustering.normalizations import normalize_entities_w_attributes_from_map
from onyx.kg.clustering.normalizations import normalize_relationships
from onyx.kg.clustering.normalizations import normalize_terms
from onyx.prompts.kg_prompts import STRATEGY_GENERATION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def analyze(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> AnalysisUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    entities = (
        state.extracted_entities_no_attributes
    )  # attribute knowledge is not required for this step
    relationships = state.extracted_relationships
    terms = state.extracted_terms
    time_filter = state.time_filter

    normalized_entities = normalize_entities(entities)

    query_graph_entities_w_attributes = normalize_entities_w_attributes_from_map(
        state.extracted_entities_w_attributes,
        normalized_entities.entity_normalization_map,
    )

    normalized_relationships = normalize_relationships(
        relationships, normalized_entities.entity_normalization_map
    )
    normalized_terms = normalize_terms(terms)
    normalized_time_filter = time_filter

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
        .replace("---terms---", "\n".join(normalized_terms.terms))
        .replace("---question---", question)
    )

    msg = [
        HumanMessage(
            content=strategy_generation_prompt,
        )
    ]
    # fast_llm = graph_config.tooling.fast_llm
    primary_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            20,
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
            strategy = approach_extraction_result.strategy
            output_format = approach_extraction_result.format
            broken_down_question = approach_extraction_result.broken_down_question
            divide_and_conquer = approach_extraction_result.divide_and_conquer
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            strategy = KGAnswerStrategy.DEEP
            output_format = KGAnswerFormat.TEXT
            broken_down_question = None
            divide_and_conquer = YesNoEnum.NO
        if strategy is None or output_format is None:
            raise ValueError(f"Invalid strategy: {cleaned_response}")

    except Exception as e:
        logger.error(f"Error in strategy generation: {e}")
        raise e

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece="\n".join(normalized_entities.entities),
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )
    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece="\n".join(normalized_relationships.relationships),
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece="\n".join(query_graph_entities),
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )
    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece="\n".join(query_graph_relationships),
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=strategy.value,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=output_format.value,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # dispatch_main_answer_stop_info(0, writer)

    return AnalysisUpdate(
        normalized_core_entities=normalized_entities.entities,
        normalized_core_relationships=normalized_relationships.relationships,
        query_graph_entities_no_attributes=query_graph_entities,
        query_graph_entities_w_attributes=query_graph_entities_w_attributes,
        query_graph_relationships=query_graph_relationships,
        normalized_terms=normalized_terms.terms,
        normalized_time_filter=normalized_time_filter,
        strategy=strategy,
        broken_down_question=broken_down_question,
        output_format=output_format,
        divide_and_conquer=divide_and_conquer,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="analyze",
                node_start_time=node_start_time,
            )
        ],
    )
