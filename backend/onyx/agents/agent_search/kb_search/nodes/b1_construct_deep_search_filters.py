from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import DeepSearchFilterUpdate
from onyx.agents.agent_search.kb_search.states import KGVespaFilterResults
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_entity_types_with_grounded_source_name
from onyx.prompts.kg_prompts import SEARCH_FILTER_CONSTRUCTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def construct_deep_search_filters(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> DeepSearchFilterUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query

    entities_types_str = state.entities_types_str
    entities = state.query_graph_entities_no_attributes
    relationships = state.query_graph_relationships
    simple_sql_query = state.sql_query

    search_filter_construction_prompt = (
        SEARCH_FILTER_CONSTRUCTION_PROMPT.replace(
            "---entity_type_descriptions---",
            entities_types_str,
        )
        .replace(
            "---entity_filters---",
            "\n".join(entities),
        )
        .replace(
            "---relationship_filters---",
            "\n".join(relationships),
        )
        .replace(
            "---sql_query---",
            simple_sql_query or "(no SQL generated)",
        )
        .replace(
            "---question---",
            question,
        )
    )

    msg = [
        HumanMessage(
            content=search_filter_construction_prompt,
        )
    ]
    llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            15,
            llm.invoke,
            prompt=msg,
            timeout_override=15,
            max_tokens=300,
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
        cleaned_response = cleaned_response.replace("{{", '{"')
        cleaned_response = cleaned_response.replace("}}", '"}')

        try:
            vespa_filter_results = KGVespaFilterResults.model_validate_json(
                cleaned_response
            )
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            vespa_filter_results = KGVespaFilterResults(
                entity_filters=[],
                relationship_filters=[],
            )
    except Exception as e:
        logger.error(f"Error in extract_ert: {e}")
        vespa_filter_results = KGVespaFilterResults(
            entity_filters=[],
            relationship_filters=[],
        )

    if (
        state.individualized_query_results
        and len(state.individualized_query_results) > 0
    ):
        div_con_entities = [
            x["id_name"]
            for x in state.individualized_query_results
            if x["id_name"] is not None and "*" not in x["id_name"]
        ]
    elif state.query_results:

        div_con_base_values = [x.values() for x in state.query_results]
        div_con_entities = list(set([x for xs in div_con_base_values for x in xs]))
    else:
        div_con_entities = []

    logger.info(f"div_con_entities: {div_con_entities}")

    with get_session_with_current_tenant() as db_session:
        double_grounded_entity_types = get_entity_types_with_grounded_source_name(
            db_session
        )

    source_division = False

    if div_con_entities:
        for entity_type in double_grounded_entity_types:
            if entity_type.grounded_source_name.lower() in div_con_entities[0].lower():
                source_division = True
                break
    else:
        raise ValueError("No div_con_entities found")

    return DeepSearchFilterUpdate(
        vespa_filter_results=vespa_filter_results,
        div_con_entities=div_con_entities,
        source_division=source_division,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="construct deep search filters",
                node_start_time=node_start_time,
            )
        ],
    )
