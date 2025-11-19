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
from onyx.configs.kg_configs import KG_FILTER_CONSTRUCTION_TIMEOUT
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entity_type import get_entity_types_with_grounded_source_name
from onyx.kg.utils.formatting_utils import make_entity_id
from onyx.prompts.kg_prompts import SEARCH_FILTER_CONSTRUCTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout


logger = setup_logger()


def construct_deep_search_filters(
    state: MainState, config: RunnableConfig, writer: StreamWriter
) -> DeepSearchFilterUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.question

    entities_types_str = state.entities_types_str
    entities = state.query_graph_entities_no_attributes
    relationships = state.query_graph_relationships
    simple_sql_query = state.sql_query
    simple_sql_results = state.sql_query_results
    source_document_results = state.source_document_results
    if simple_sql_results:
        simple_sql_results_str = "\n".join([str(x) for x in simple_sql_results])
    else:
        simple_sql_results_str = "(no SQL results generated)"
    if source_document_results:
        source_document_results_str = "\n".join(
            [str(x) for x in source_document_results]
        )
    else:
        source_document_results_str = "(no source document results generated)"

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
            "---sql_results---",
            simple_sql_results_str or "(no SQL results generated)",
        )
        .replace(
            "---source_document_results---",
            source_document_results_str or "(no source document results generated)",
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
            KG_FILTER_CONSTRUCTION_TIMEOUT,
            llm.invoke,
            prompt=msg,
            timeout_override=15,
            max_tokens=1400,
        )

        cleaned_response = (
            str(llm_response.content)
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")

        if last_bracket == -1 or first_bracket == -1:
            raise ValueError("No valid JSON found in LLM response - no brackets found")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]
        cleaned_response = cleaned_response.replace("{{", '{"')
        cleaned_response = cleaned_response.replace("}}", '"}')

        try:

            filter_results = KGFilterConstructionResults.model_validate_json(
                cleaned_response
            )
        except ValueError:
            logger.error(
                "Failed to parse LLM response as JSON in Entity-Term Extraction"
            )
            filter_results = KGFilterConstructionResults(
                global_entity_filters=[],
                global_relationship_filters=[],
                local_entity_filters=[],
                source_document_filters=[],
                structure=[],
            )

    except Exception as e:
        logger.error(f"Error in construct_deep_search_filters: {e}")
        filter_results = KGFilterConstructionResults(
            global_entity_filters=[],
            global_relationship_filters=[],
            local_entity_filters=[],
            source_document_filters=[],
            structure=[],
        )

    div_con_structure = filter_results.structure

    logger.info(f"div_con_structure: {div_con_structure}")

    with get_session_with_current_tenant() as db_session:
        double_grounded_entity_types = get_entity_types_with_grounded_source_name(
            db_session
        )

    source_division = False

    if div_con_structure:
        for entity_type in double_grounded_entity_types:
            # entity_type is guaranteed to have grounded_source_name
            if (
                cast(str, entity_type.grounded_source_name).lower()
                in div_con_structure[0].lower()
            ):
                source_division = True
                break

    return DeepSearchFilterUpdate(
        vespa_filter_results=filter_results,
        div_con_entities=div_con_structure,
        source_division=source_division,
        global_entity_filters=[
            make_entity_id(global_filter, "*")
            for global_filter in filter_results.global_entity_filters
        ],
        global_relationship_filters=filter_results.global_relationship_filters,
        local_entity_filters=filter_results.local_entity_filters,
        source_filters=filter_results.source_document_filters,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="construct deep search filters",
                node_start_time=node_start_time,
            )
        ],
        step_results=[],
    )
