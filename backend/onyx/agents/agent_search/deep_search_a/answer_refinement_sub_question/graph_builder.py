from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.nodes.answer_check import (
    answer_check,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.nodes.answer_generation import (
    answer_generation,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.nodes.format_answer import (
    format_answer,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.nodes.ingest_retrieval import (
    ingest_retrieval,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionInput,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionOutput,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.deep_search_a.answer_refinement_sub_question.edges import (
    send_to_expanded_refined_retrieval,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.graph_builder import (
    expanded_retrieval_graph_builder,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def answer_refined_query_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=AnswerQuestionState,
        input=AnswerQuestionInput,
        output=AnswerQuestionOutput,
    )

    ### Add nodes ###

    expanded_retrieval = expanded_retrieval_graph_builder().compile()
    graph.add_node(
        node="refined_sub_question_expanded_retrieval",
        action=expanded_retrieval,
    )
    graph.add_node(
        node="refined_sub_answer_check",
        action=answer_check,
    )
    graph.add_node(
        node="refined_sub_answer_generation",
        action=answer_generation,
    )
    graph.add_node(
        node="format_refined_sub_answer",
        action=format_answer,
    )
    graph.add_node(
        node="ingest_refined_retrieval",
        action=ingest_retrieval,
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
        end_key="refined_sub_answer_generation",
    )
    graph.add_edge(
        start_key="refined_sub_answer_generation",
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
    from onyx.db.engine import get_session_context_manager
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = answer_refined_query_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()
    search_request = SearchRequest(
        query="what can you do with onyx or danswer?",
    )
    with get_session_context_manager() as db_session:
        inputs = AnswerQuestionInput(
            question="what can you do with onyx?",
            question_id="0_0",
            log_messages=[],
        )
        for thing in compiled_graph.stream(
            input=inputs,
            # debug=True,
            # subgraphs=True,
        ):
            logger.debug(thing)
        # output = compiled_graph.invoke(inputs)
        #  logger.debug(output)
