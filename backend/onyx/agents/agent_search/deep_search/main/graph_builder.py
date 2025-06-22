from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.graph_builder import (
    generate_initial_answer_graph_builder,
)
from onyx.agents.agent_search.deep_search.main.edges import (
    continue_to_refined_answer_or_end,
)
from onyx.agents.agent_search.deep_search.main.edges import (
    parallelize_refined_sub_question_answering,
)
from onyx.agents.agent_search.deep_search.main.edges import (
    route_initial_tool_choice,
)
from onyx.agents.agent_search.deep_search.main.nodes.compare_answers import (
    compare_answers,
)
from onyx.agents.agent_search.deep_search.main.nodes.create_refined_sub_questions import (
    create_refined_sub_questions,
)
from onyx.agents.agent_search.deep_search.main.nodes.decide_refinement_need import (
    decide_refinement_need,
)
from onyx.agents.agent_search.deep_search.main.nodes.extract_entities_terms import (
    extract_entities_terms,
)
from onyx.agents.agent_search.deep_search.main.nodes.generate_validate_refined_answer import (
    generate_validate_refined_answer,
)
from onyx.agents.agent_search.deep_search.main.nodes.ingest_refined_sub_answers import (
    ingest_refined_sub_answers,
)
from onyx.agents.agent_search.deep_search.main.nodes.persist_agent_results import (
    persist_agent_results,
)
from onyx.agents.agent_search.deep_search.main.nodes.start_agent_search import (
    start_agent_search,
)
from onyx.agents.agent_search.deep_search.main.states import MainInput
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.deep_search.refinement.consolidate_sub_answers.graph_builder import (
    answer_refined_query_graph_builder,
)
from onyx.agents.agent_search.orchestration.nodes.call_tool import call_tool
from onyx.agents.agent_search.orchestration.nodes.choose_tool import choose_tool
from onyx.agents.agent_search.orchestration.nodes.prepare_tool_input import (
    prepare_tool_input,
)
from onyx.agents.agent_search.orchestration.nodes.use_tool_response import (
    basic_use_tool_response,
)
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.utils.logger import setup_logger

logger = setup_logger()

test_mode = False


def agent_search_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the main agent search process.
    """
    graph = StateGraph(
        state_schema=MainState,
        input=MainInput,
    )

    # Prepare the tool input
    graph.add_node(
        node="prepare_tool_input",
        action=prepare_tool_input,
    )

    # Choose the initial tool
    graph.add_node(
        node="choose_tool",
        action=choose_tool,
    )

    # Call the tool, if required
    graph.add_node(
        node="call_tool",
        action=call_tool,
    )

    # Use the tool response
    graph.add_node(
        node="basic_use_tool_response",
        action=basic_use_tool_response,
    )

    # Start the agent search process
    graph.add_node(
        node="start_agent_search",
        action=start_agent_search,
    )

    # The sub-graph for the initial answer generation
    generate_initial_answer_subgraph = generate_initial_answer_graph_builder().compile()
    graph.add_node(
        node="generate_initial_answer_subgraph",
        action=generate_initial_answer_subgraph,
    )

    # Create the refined sub-questions
    graph.add_node(
        node="create_refined_sub_questions",
        action=create_refined_sub_questions,
    )

    # Subgraph for the refined sub-answer generation
    answer_refined_question = answer_refined_query_graph_builder().compile()
    graph.add_node(
        node="answer_refined_question_subgraphs",
        action=answer_refined_question,
    )

    # Ingest the refined sub-answers
    graph.add_node(
        node="ingest_refined_sub_answers",
        action=ingest_refined_sub_answers,
    )

    # Node to generate the refined answer
    graph.add_node(
        node="generate_validate_refined_answer",
        action=generate_validate_refined_answer,
    )

    # Early node to extract the entities and terms from the initial answer,
    # This information is used to inform the creation the refined sub-questions
    graph.add_node(
        node="extract_entity_term",
        action=extract_entities_terms,
    )

    # Decide if the answer needs to be refined (currently always true)
    graph.add_node(
        node="decide_refinement_need",
        action=decide_refinement_need,
    )

    # Compare the initial and refined answers, and determine whether
    # the refined answer is sufficiently better
    graph.add_node(
        node="compare_answers",
        action=compare_answers,
    )

    # Log the results. This will log the stats as well as the answers, sub-questions, and sub-answers
    graph.add_node(
        node="logging_node",
        action=persist_agent_results,
    )

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="prepare_tool_input")

    graph.add_edge(
        start_key="prepare_tool_input",
        end_key="choose_tool",
    )

    graph.add_conditional_edges(
        "choose_tool",
        route_initial_tool_choice,
        ["call_tool", "start_agent_search", "logging_node"],
    )

    graph.add_edge(
        start_key="call_tool",
        end_key="basic_use_tool_response",
    )
    graph.add_edge(
        start_key="basic_use_tool_response",
        end_key="logging_node",
    )

    graph.add_edge(
        start_key="start_agent_search",
        end_key="generate_initial_answer_subgraph",
    )

    graph.add_edge(
        start_key="start_agent_search",
        end_key="extract_entity_term",
    )

    # Wait for the initial answer generation and the entity/term extraction to be complete
    # before deciding if a refinement is needed.
    graph.add_edge(
        start_key=["generate_initial_answer_subgraph", "extract_entity_term"],
        end_key="decide_refinement_need",
    )

    graph.add_conditional_edges(
        source="decide_refinement_need",
        path=continue_to_refined_answer_or_end,
        path_map=["create_refined_sub_questions", "logging_node"],
    )

    graph.add_conditional_edges(
        source="create_refined_sub_questions",
        path=parallelize_refined_sub_question_answering,
        path_map=["answer_refined_question_subgraphs"],
    )
    graph.add_edge(
        start_key="answer_refined_question_subgraphs",
        end_key="ingest_refined_sub_answers",
    )

    graph.add_edge(
        start_key="ingest_refined_sub_answers",
        end_key="generate_validate_refined_answer",
    )

    graph.add_edge(
        start_key="generate_validate_refined_answer",
        end_key="compare_answers",
    )
    graph.add_edge(
        start_key="compare_answers",
        end_key="logging_node",
    )

    graph.add_edge(
        start_key="logging_node",
        end_key=END,
    )

    return graph


if __name__ == "__main__":
    pass

    from onyx.db.engine.sql_engine import get_session_with_current_tenant
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = agent_search_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()

    with get_session_with_current_tenant() as db_session:
        search_request = SearchRequest(query="Who created Excel?")
        graph_config = get_test_config(
            db_session, primary_llm, fast_llm, search_request
        )

        inputs = MainInput(log_messages=[])

        for thing in compiled_graph.stream(
            input=inputs,
            config={"configurable": {"config": graph_config}},
            stream_mode="custom",
            subgraphs=True,
        ):
            logger.debug(thing)
