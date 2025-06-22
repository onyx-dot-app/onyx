from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.nodes.check_sub_answer import (
    check_sub_answer,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.nodes.format_sub_answer import (
    format_sub_answer,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.nodes.generate_sub_answer import (
    generate_sub_answer,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.nodes.ingest_retrieved_documents import (
    ingest_retrieved_documents,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionOutput,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    SubQuestionAnsweringInput,
)
from onyx.agents.agent_search.deep_search.refinement.consolidate_sub_answers.edges import (
    send_to_expanded_refined_retrieval,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.graph_builder import (
    expanded_retrieval_graph_builder,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def answer_refined_query_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the refined sub-answer generation process.
    """
    graph = StateGraph(
        state_schema=AnswerQuestionState,
        input=SubQuestionAnsweringInput,
        output=AnswerQuestionOutput,
    )

    ### Add nodes ###

    # Subgraph for the expanded retrieval process
    expanded_retrieval = expanded_retrieval_graph_builder().compile()
    graph.add_node(
        node="refined_sub_question_expanded_retrieval",
        action=expanded_retrieval,
    )

    # Ingest the retrieved documents
    graph.add_node(
        node="ingest_refined_retrieval",
        action=ingest_retrieved_documents,
    )

    # Generate the refined sub-answer
    graph.add_node(
        node="generate_refined_sub_answer",
        action=generate_sub_answer,
    )

    # Check if the refined sub-answer is correct
    graph.add_node(
        node="refined_sub_answer_check",
        action=check_sub_answer,
    )

    # Format the refined sub-answer
    graph.add_node(
        node="format_refined_sub_answer",
        action=format_sub_answer,
    )

    ### Add edges ###

    graph.add_conditional_edges(
        source=START,
        path=send_to_expanded_refined_retrieval,
        path_map=["refined_sub_question_expanded_retrieval"],
    )
    graph.add_edge(
        start_key="refined_sub_question_expanded_retrieval",
        end_key="ingest_refined_retrieval",
    )
    graph.add_edge(
        start_key="ingest_refined_retrieval",
        end_key="generate_refined_sub_answer",
    )
    graph.add_edge(
        start_key="generate_refined_sub_answer",
        end_key="refined_sub_answer_check",
    )
    graph.add_edge(
        start_key="refined_sub_answer_check",
        end_key="format_refined_sub_answer",
    )
    graph.add_edge(
        start_key="format_refined_sub_answer",
        end_key=END,
    )

    return graph


if __name__ == "__main__":
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = answer_refined_query_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()
    search_request = SearchRequest(
        query="what can you do with onyx or danswer?",
    )
    with get_session_with_current_tenant() as db_session:
        inputs = SubQuestionAnsweringInput(
            question="what can you do with onyx?",
            question_id="0_0",
            log_messages=[],
        )
        for thing in compiled_graph.stream(
            input=inputs,
            stream_mode="custom",
        ):
            logger.debug(thing)
