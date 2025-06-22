from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.edges import (
    parallel_retrieval_edge,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.expand_queries import (
    expand_queries,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.format_queries import (
    format_queries,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.format_results import (
    format_results,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.kickoff_verification import (
    kickoff_verification,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.rerank_documents import (
    rerank_documents,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.retrieve_documents import (
    retrieve_documents,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.nodes.verify_documents import (
    verify_documents,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalOutput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.utils.logger import setup_logger

logger = setup_logger()


def expanded_retrieval_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the expanded retrieval process.
    """
    graph = StateGraph(
        state_schema=ExpandedRetrievalState,
        input=ExpandedRetrievalInput,
        output=ExpandedRetrievalOutput,
    )

    ### Add nodes ###

    # Convert the question into multiple sub-queries
    graph.add_node(
        node="expand_queries",
        action=expand_queries,
    )

    # Format the sub-queries into a list of strings
    graph.add_node(
        node="format_queries",
        action=format_queries,
    )

    # Retrieve the documents for each sub-query
    graph.add_node(
        node="retrieve_documents",
        action=retrieve_documents,
    )

    # Start verification process that the documents are relevant to the question (not the query)
    graph.add_node(
        node="kickoff_verification",
        action=kickoff_verification,
    )

    # Verify that a given document is relevant to the question (not the query)
    graph.add_node(
        node="verify_documents",
        action=verify_documents,
    )

    # Rerank the documents that have been verified
    graph.add_node(
        node="rerank_documents",
        action=rerank_documents,
    )

    # Format the results into a list of strings
    graph.add_node(
        node="format_results",
        action=format_results,
    )

    ### Add edges ###
    graph.add_edge(
        start_key=START,
        end_key="expand_queries",
    )
    graph.add_edge(
        start_key="expand_queries",
        end_key="format_queries",
    )

    graph.add_conditional_edges(
        source="format_queries",
        path=parallel_retrieval_edge,
        path_map=["retrieve_documents"],
    )
    graph.add_edge(
        start_key="retrieve_documents",
        end_key="kickoff_verification",
    )
    graph.add_edge(
        start_key="verify_documents",
        end_key="rerank_documents",
    )
    graph.add_edge(
        start_key="rerank_documents",
        end_key="format_results",
    )
    graph.add_edge(
        start_key="format_results",
        end_key=END,
    )

    return graph


if __name__ == "__main__":
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = expanded_retrieval_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()
    search_request = SearchRequest(
        query="what can you do with onyx or danswer?",
    )

    with get_session_with_current_tenant() as db_session:
        graph_config, search_tool = get_test_config(
            db_session, primary_llm, fast_llm, search_request
        )
        inputs = ExpandedRetrievalInput(
            question="what can you do with onyx?",
            base_search=False,
            sub_question_id=None,
            log_messages=[],
        )
        for thing in compiled_graph.stream(
            input=inputs,
            config={"configurable": {"config": graph_config}},
            stream_mode="custom",
            subgraphs=True,
        ):
            logger.debug(thing)
