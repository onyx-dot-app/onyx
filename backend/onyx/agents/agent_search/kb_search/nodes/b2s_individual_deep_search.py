from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import DeepSearchFilterUpdate
from onyx.agents.agent_search.kb_search.states import KGFilterConstructionResults
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.prompts.kg_prompts import SEARCH_FILTER_CONSTRUCTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def individual_deep_search(
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
            vespa_filter_results = KGFilterConstructionResults.model_validate_json(
                cleaned_response
            )
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            vespa_filter_results = KGFilterConstructionResults(
                entity_filters=[],
                relationship_filters=[],
            )
    except Exception as e:
        logger.error(f"Error in extract_ert: {e}")
        vespa_filter_results = KGFilterConstructionResults(
            entity_filters=[],
            relationship_filters=[],
        )

    if state.sql_query_results:
        div_con_entities = [
            x["id_name"] for x in state.sql_query_results if x["id_name"] is not None
        ]
    else:
        div_con_entities = []

    return DeepSearchFilterUpdate(
        vespa_filter_results=vespa_filter_results,
        div_con_entities=div_con_entities,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="construct deep search filters",
                node_start_time=node_start_time,
            )
        ],
    )
