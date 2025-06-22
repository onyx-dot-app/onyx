from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.edges import (
    send_to_expanded_retrieval,
)
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
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.graph_builder import (
    expanded_retrieval_graph_builder,
)
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.utils.logger import setup_logger

logger = setup_logger()


def answer_query_graph_builder() -> StateGraph:
    """
    LangGraph sub-graph builder for the initial individual sub-answer generation.
    """
    graph = StateGraph(
        state_schema=AnswerQuestionState,
        input=SubQuestionAnsweringInput,
        output=AnswerQuestionOutput,
    )

    ### Add nodes ###

    # The sub-graph that executes the expanded retrieval process for a sub-question
    expanded_retrieval = expanded_retrieval_graph_builder().compile()
    graph.add_node(
        node="initial_sub_question_expanded_retrieval",
        action=expanded_retrieval,
    )

    # The node that ingests the retrieved documents and puts them into the proper
    # state keys.
    graph.add_node(
        node="ingest_retrieval",
        action=ingest_retrieved_documents,
    )

    # The node that generates the sub-answer
    graph.add_node(
        node="generate_sub_answer",
        action=generate_sub_answer,
    )

    # The node that checks the sub-answer
    graph.add_node(
        node="answer_check",
        action=check_sub_answer,
    )

    # The node that formats the sub-answer for the following initial answer generation
    graph.add_node(
        node="format_answer",
        action=format_sub_answer,
    )

    ### Add edges ###

    graph.add_conditional_edges(
        source=START,
        path=send_to_expanded_retrieval,
        path_map=["initial_sub_question_expanded_retrieval"],
    )
    graph.add_edge(
        start_key="initial_sub_question_expanded_retrieval",
        end_key="ingest_retrieval",
    )
    graph.add_edge(
        start_key="ingest_retrieval",
        end_key="generate_sub_answer",
    )
    graph.add_edge(
        start_key="generate_sub_answer",
        end_key="answer_check",
    )
    graph.add_edge(
        start_key="answer_check",
        end_key="format_answer",
    )
    graph.add_edge(
        start_key="format_answer",
        end_key=END,
    )

    return graph


if __name__ == "__main__":
    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = answer_query_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()
    search_request = SearchRequest(
        query="what can you do with onyx or danswer?",
    )
    with get_session_with_current_tenant() as db_session:
        graph_config, search_tool = get_test_config(
            db_session, primary_llm, fast_llm, search_request
        )
        inputs = SubQuestionAnsweringInput(
            question="what can you do with onyx?",
            question_id="0_0",
            log_messages=[],
        )
        for thing in compiled_graph.stream(
            input=inputs,
            config={"configurable": {"config": graph_config}},
        ):
            logger.debug(thing)
