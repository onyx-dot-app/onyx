from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.models import KGQuestionExtractionResult
from onyx.agents.agent_search.kb_search.states import (
    ERTExtractionUpdate,
)
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.kg.extractions.extraction_processing import _get_entity_types_str
from onyx.prompts.kg_prompts import QUERY_EXTRACTION_PROMPT
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

    query_extraction_pre_prompt = QUERY_EXTRACTION_PROMPT.format(
        entity_types=_get_entity_types_str(active=True)
    )
    query_extraction_prompt = query_extraction_pre_prompt.replace(
        "---content---", question
    )

    msg = [
        HumanMessage(
            content=query_extraction_prompt,
        )
    ]
    fast_llm = graph_config.tooling.fast_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            5,
            fast_llm.invoke,
            prompt=msg,
            timeout_override=5,
            max_tokens=300,
        )

        cleaned_response = (
            str(llm_response.content).replace("```json\n", "").replace("\n```", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]

        try:
            entity_extraction_result = KGQuestionExtractionResult.model_validate_json(
                cleaned_response
            )
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            entity_extraction_result = KGQuestionExtractionResult(
                entities=[],
                relationships=[],
                terms=[],
            )
    except Exception as e:
        logger.error(f"Error in extract_ert: {e}")
        entity_extraction_result = KGQuestionExtractionResult(
            entities=[], relationships=[], terms=[]
        )

    ert_entities_string = f"Entities: {entity_extraction_result.entities}\n"
    ert_relationships_string = (
        f"Relationships: {entity_extraction_result.relationships}\n"
    )
    ert_terms_string = f"Terms: {entity_extraction_result.terms}"

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=ert_entities_string,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )
    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=ert_relationships_string,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )
    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=ert_terms_string,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )
    dispatch_main_answer_stop_info(0, writer)

    return ERTExtractionUpdate(
        entities=entity_extraction_result.entities,
        relationships=entity_extraction_result.relationships,
        terms=entity_extraction_result.terms,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="extract entities terms",
                node_start_time=node_start_time,
            )
        ],
    )
