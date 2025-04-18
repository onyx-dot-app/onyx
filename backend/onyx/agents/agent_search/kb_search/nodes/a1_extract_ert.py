from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.models import KGQuestionEntityExtractionResult
from onyx.agents.agent_search.kb_search.models import (
    KGQuestionRelationshipExtractionResult,
)
from onyx.agents.agent_search.kb_search.states import (
    ERTExtractionUpdate,
)
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.relationships import get_allowed_relationship_type_pairs
from onyx.kg.extractions.extraction_processing import get_entity_types_str
from onyx.kg.extractions.extraction_processing import get_relationship_types_str
from onyx.prompts.kg_prompts import QUERY_ENTITY_EXTRACTION_PROMPT
from onyx.prompts.kg_prompts import QUERY_RELATIONSHIP_EXTRACTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def extract_ert(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ERTExtractionUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query

    # first four lines duplicates from generate_initial_answer
    question = graph_config.inputs.search_request.query
    today_date = datetime.now().strftime("%A, %Y-%m-%d")

    all_entity_types = get_entity_types_str(active=None)
    all_relationship_types = get_relationship_types_str(active=None)

    ### get the entities, terms, and filters

    query_extraction_pre_prompt = QUERY_ENTITY_EXTRACTION_PROMPT.format(
        entity_types=all_entity_types,
        relationship_types=all_relationship_types,
    )

    query_extraction_prompt = (
        query_extraction_pre_prompt.replace("---content---", question)
        .replace("---today_date---", today_date)
        .replace("{{", "{")
        .replace("}}", "}")
    )

    msg = [
        HumanMessage(
            content=query_extraction_prompt,
        )
    ]
    fast_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            15,
            fast_llm.invoke,
            prompt=msg,
            timeout_override=15,
            max_tokens=300,
        )

        cleaned_response = (
            str(llm_response.content)
            .replace("{{", "{")
            .replace("}}", "}")
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]

        try:
            entity_extraction_result = (
                KGQuestionEntityExtractionResult.model_validate_json(cleaned_response)
            )
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            entity_extraction_result = KGQuestionEntityExtractionResult(
                entities=[],
                terms=[],
                time_filter="",
            )
    except Exception as e:
        logger.error(f"Error in extract_ert: {e}")
        entity_extraction_result = KGQuestionEntityExtractionResult(
            entities=[],
            terms=[],
            time_filter="",
        )

    # remove the attribute filters from the entities to for the purpose of the relationship
    entities_no_attributes = [
        entity.split("--")[0] for entity in entity_extraction_result.entities
    ]
    entities_string_for_relationships = f"Entities: {entities_no_attributes}\n"
    ert_entities_string = f"Entities: {entities_string_for_relationships}\n"

    ### get the relationships

    # find the relationship types that match the extracted entity types

    with get_session_with_current_tenant() as db_session:
        allowed_relationship_pairs = get_allowed_relationship_type_pairs(
            db_session, entity_extraction_result.entities
        )

    query_relationship_extraction_prompt = (
        QUERY_RELATIONSHIP_EXTRACTION_PROMPT.replace("---question---", question)
        .replace("---today_date---", today_date)
        .replace(
            "---relationship_type_options---",
            "  - " + "\n  - ".join(allowed_relationship_pairs),
        )
        .replace("---identified_entities---", ert_entities_string)
        .replace("---entity_types---", all_entity_types)
        .replace("{{", "{")
        .replace("}}", "}")
    )

    msg = [
        HumanMessage(
            content=query_relationship_extraction_prompt,
        )
    ]
    fast_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            15,
            fast_llm.invoke,
            prompt=msg,
            timeout_override=15,
            max_tokens=300,
        )

        cleaned_response = (
            str(llm_response.content)
            .replace("{{", "{")
            .replace("}}", "}")
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]
        cleaned_response = cleaned_response.replace(" ", "")
        cleaned_response = cleaned_response.replace("{{", '{"')
        cleaned_response = cleaned_response.replace("}}", '"}')

        try:
            relationship_extraction_result = (
                KGQuestionRelationshipExtractionResult.model_validate_json(
                    cleaned_response
                )
            )
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            relationship_extraction_result = KGQuestionRelationshipExtractionResult(
                relationships=[],
            )
    except Exception as e:
        logger.error(f"Error in extract_ert: {e}")
        relationship_extraction_result = KGQuestionRelationshipExtractionResult(
            relationships=[],
        )

    # ert_relationships_string = (
    #     f"Relationships: {relationship_extraction_result.relationships}\n"
    # )

    ##

    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=ert_entities_string,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )
    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=ert_relationships_string,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )
    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=ert_terms_string,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )
    # write_custom_event(
    #     "initial_agent_answer",
    #     AgentAnswerPiece(
    #         answer_piece=ert_time_filter_string,
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )
    # dispatch_main_answer_stop_info(0, writer)

    return ERTExtractionUpdate(
        entities_types_str=all_entity_types,
        relationship_types_str=all_relationship_types,
        extracted_entities_w_attributes=entity_extraction_result.entities,
        extracted_entities_no_attributes=entities_no_attributes,
        extracted_relationships=relationship_extraction_result.relationships,
        extracted_terms=entity_extraction_result.terms,
        time_filter=entity_extraction_result.time_filter,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="extract entities terms",
                node_start_time=node_start_time,
            )
        ],
    )
