from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.graph_builder import (
    answer_query_graph_builder,
)
from onyx.agents.agent_search.deep_search.initial.generate_sub_answers.edges import (
    parallelize_initial_sub_question_answering,
)
from onyx.agents.agent_search.deep_search.initial.generate_sub_answers.nodes.decompose_orig_question import (
    decompose_orig_question,
)
from onyx.agents.agent_search.deep_search.initial.generate_sub_answers.nodes.format_initial_sub_answers import (
    format_initial_sub_answers,
)
from onyx.agents.agent_search.deep_search.initial.generate_sub_answers.states import (
    SubQuestionAnsweringInput,
)
from onyx.agents.agent_search.deep_search.initial.generate_sub_answers.states import (
    SubQuestionAnsweringState,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

test_mode = False


def generate_sub_answers_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the initial sub-answer generation process.
    It generates the initial sub-questions and produces the answers.
    """

    graph = StateGraph(
        state_schema=SubQuestionAnsweringState,
        input=SubQuestionAnsweringInput,
    )

    # Decompose the original question into sub-questions
    graph.add_node(
        node="decompose_orig_question",
        action=decompose_orig_question,
    )

    # The sub-graph that executes the initial sub-question answering for
    # each of the sub-questions.
    answer_sub_question_subgraphs = answer_query_graph_builder().compile()
    graph.add_node(
        node="answer_sub_question_subgraphs",
        action=answer_sub_question_subgraphs,
    )

    # Node that collects and formats the initial sub-question answers
    graph.add_node(
        node="format_initial_sub_question_answers",
        action=format_initial_sub_answers,
    )

    graph.add_edge(
        start_key=START,
        end_key="decompose_orig_question",
    )

    graph.add_conditional_edges(
        source="decompose_orig_question",
        path=parallelize_initial_sub_question_answering,
        path_map=["answer_sub_question_subgraphs"],
    )
    graph.add_edge(
        start_key=["answer_sub_question_subgraphs"],
        end_key="format_initial_sub_question_answers",
    )

    graph.add_edge(
        start_key="format_initial_sub_question_answers",
        end_key=END,
    )

    return graph
