from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import AnalysisUpdate
from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
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
from onyx.kg.clustering.normalizations import normalize_entities
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
    entities = state.entities
    relationships = state.relationships
    terms = state.terms
    time_filter = state.time_filter

    normalized_entities = normalize_entities(entities)
    normalized_relationships = normalize_relationships(
        relationships, normalized_entities.entity_normalization_map
    )
    normalized_terms = normalize_terms(terms)
    normalized_time_filter = time_filter

    strategy_generation_prompt = (
        STRATEGY_GENERATION_PROMPT.replace(
            "---entities---", "\n".join(normalized_entities.entities)
        )
        .replace(
            "---relationships---", "\n".join(normalized_relationships.relationships)
        )
        .replace("---terms---", "\n".join(normalized_terms.terms))
        .replace("---question---", question)
    )

    msg = [
        HumanMessage(
            content=strategy_generation_prompt,
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
            max_tokens=5,
        )

        cleaned_response = (
            str(llm_response.content).replace("```json\n", "").replace("\n```", "")
        )

        if KGAnswerStrategy.DEEP.value in cleaned_response:
            strategy = KGAnswerStrategy.DEEP
        elif KGAnswerStrategy.SIMPLE.value in cleaned_response:
            strategy = KGAnswerStrategy.SIMPLE
        else:
            raise ValueError(f"Invalid strategy: {cleaned_response}")
    except Exception as e:
        logger.error(f"Error in strategy generation: {e}")
        raise e

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece="\n".join(normalized_entities.entities),
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )
    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece="\n".join(normalized_relationships.relationships),
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=strategy.value,
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    dispatch_main_answer_stop_info(0, writer)

    return AnalysisUpdate(
        normalized_entities=normalized_entities.entities,
        normalized_relationships=normalized_relationships.relationships,
        normalized_terms=normalized_terms.terms,
        normalized_time_filter=normalized_time_filter,
        strategy=strategy,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="analyze",
                node_start_time=node_start_time,
            )
        ],
    )
