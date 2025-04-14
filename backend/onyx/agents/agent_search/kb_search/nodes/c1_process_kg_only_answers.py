from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import ResultsDataUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.models import ReferenceResults
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.db.document import get_base_llm_doc_information
from onyx.db.engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _general_format(result: dict[str, Any]) -> str:
    name = result.get("name")
    entity_type_id_name = result.get("entity_type_id_name")
    result.get("id_name")

    if entity_type_id_name:
        return f"{entity_type_id_name.capitalize()}: {name}"
    else:
        return f"{name}"


def _generate_reference_results(
    individualized_query_results: list[dict[str, Any]],
) -> ReferenceResults:
    """
    Generate reference results from the query results data string.
    """

    citations: list[str] = []
    general_entities = []

    # get all entities that correspond to an Onu=yx document
    document_ids: list[str] = [
        cast(str, x.get("document_id"))
        for x in individualized_query_results
        if x.get("document_id")
    ]

    with get_session_with_current_tenant() as session:
        llm_doc_information_results = get_base_llm_doc_information(
            session, document_ids
        )

    for llm_doc_information_result in llm_doc_information_results:
        citations.append(llm_doc_information_result.center_chunk.semantic_identifier)

    for result in individualized_query_results:
        document_id: str | None = result.get("document_id")

        if not document_id:
            general_entities.append(_general_format(result))

    return ReferenceResults(citations=citations, general_entities=general_entities)


def process_kg_only_answers(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ResultsDataUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    graph_config.inputs.search_request.query
    query_results = state.query_results
    individualized_query_results = state.individualized_query_results

    query_results_list = []

    if query_results:
        for query_result in query_results:
            query_results_list.append(str(query_result).replace(":", ": ").capitalize())
    else:
        raise ValueError("No query results were found")

    query_results_data_str = "\n".join(query_results_list)

    if individualized_query_results:
        reference_results = _generate_reference_results(individualized_query_results)
    else:
        reference_results = None

    return ResultsDataUpdate(
        query_results_data_str=query_results_data_str,
        individualized_query_results_data_str="",
        reference_results=reference_results,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="kg query results data processing",
                node_start_time=node_start_time,
            )
        ],
    )
