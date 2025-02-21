from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.nodes.generate_initial_answer import (
    generate_initial_answer,
)
from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.nodes.validate_initial_answer import (
    validate_initial_answer,
)
from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.states import (
    SubQuestionRetrievalInput,
)
from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.states import (
    SubQuestionRetrievalState,
)
from onyx.agents.agent_search.deep_search.initial.generate_sub_answers.graph_builder import (
    generate_sub_answers_graph_builder,
)
from onyx.agents.agent_search.deep_search.initial.retrieve_orig_question_docs.graph_builder import (
    retrieve_orig_question_docs_graph_builder,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generate_initial_answer_graph_builder(test_mode: bool = False) -> StateGraph:
    """
    LangGraph graph builder for the initial answer generation.
    """
    graph = StateGraph(
        state_schema=SubQuestionRetrievalState,
        input=SubQuestionRetrievalInput,
    )

    # The sub-graph that generates the initial sub-answers
    generate_sub_answers = generate_sub_answers_graph_builder().compile()
    graph.add_node(
        node="generate_sub_answers_subgraph",
        action=generate_sub_answers,
    )

    # The sub-graph that retrieves the original question documents. This is run
    # in parallel with the sub-answer generation process
    retrieve_orig_question_docs = retrieve_orig_question_docs_graph_builder().compile()
    graph.add_node(
        node="retrieve_orig_question_docs_subgraph_wrapper",
        action=retrieve_orig_question_docs,
    )

    # Node that generates the initial answer using the results of the previous
    # two sub-graphs
    graph.add_node(
        node="generate_initial_answer",
        action=generate_initial_answer,
    )

    # Node that validates the initial answer
    graph.add_node(
        node="validate_initial_answer",
        action=validate_initial_answer,
    )

    ### Add edges ###

    graph.add_edge(
        start_key=START,
        end_key="retrieve_orig_question_docs_subgraph_wrapper",
    )

    graph.add_edge(
        start_key=START,
        end_key="generate_sub_answers_subgraph",
    )

    # Wait for both, the original question docs and the sub-answers to be generated before proceeding
    graph.add_edge(
        start_key=[
            "retrieve_orig_question_docs_subgraph_wrapper",
            "generate_sub_answers_subgraph",
        ],
        end_key="generate_initial_answer",
    )

    graph.add_edge(
        start_key="generate_initial_answer",
        end_key="validate_initial_answer",
    )

    graph.add_edge(
        start_key="validate_initial_answer",
        end_key=END,
    )

    return graph
