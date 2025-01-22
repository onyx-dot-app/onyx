from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.graph_builder import (
    answer_query_graph_builder,
)
from onyx.agents.agent_search.deep_search_a.answer_refinement_sub_question.graph_builder import (
    answer_refined_query_graph_builder,
)
from onyx.agents.agent_search.deep_search_a.base_raw_search.graph_builder import (
    base_raw_search_graph_builder,
)
from onyx.agents.agent_search.deep_search_a.main.edges import (
    continue_to_refined_answer_or_end,
)
from onyx.agents.agent_search.deep_search_a.main.edges import (
    parallelize_initial_sub_question_answering,
)
from onyx.agents.agent_search.deep_search_a.main.edges import (
    parallelize_refined_sub_question_answering,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.agent_logging import (
    agent_logging,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.agent_path_decision import (
    agent_path_decision,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.agent_path_routing import (
    agent_path_routing,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.agent_search_start import (
    agent_search_start,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.direct_llm_handling import (
    direct_llm_handling,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.entity_term_extraction_llm import (
    entity_term_extraction_llm,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.generate_initial_answer import (
    generate_initial_answer,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.generate_refined_answer import (
    generate_refined_answer,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.ingest_initial_base_retrieval import (
    ingest_initial_base_retrieval,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.ingest_initial_sub_question_answers import (
    ingest_initial_sub_question_answers,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.ingest_refined_answers import (
    ingest_refined_answers,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.initial_answer_quality_check import (
    initial_answer_quality_check,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.initial_sub_question_creation import (
    initial_sub_question_creation,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.refined_answer_decision import (
    refined_answer_decision,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.refined_sub_question_creation import (
    refined_sub_question_creation,
)
from onyx.agents.agent_search.deep_search_a.main.nodes.retrieval_consolidation import (
    retrieval_consolidation,
)
from onyx.agents.agent_search.deep_search_a.main.states import MainInput
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.utils.logger import setup_logger

logger = setup_logger()

test_mode = False


def main_graph_builder(test_mode: bool = False) -> StateGraph:
    graph = StateGraph(
        state_schema=MainState,
        input=MainInput,
    )

    graph.add_node(
        node="agent_path_decision",
        action=agent_path_decision,
    )

    graph.add_node(
        node="agent_path_routing",
        action=agent_path_routing,
    )

    graph.add_node(
        node="LLM",
        action=direct_llm_handling,
    )

    graph.add_node(
        node="agent_search_start",
        action=agent_search_start,
    )

    graph.add_node(
        node="initial_sub_question_creation",
        action=initial_sub_question_creation,
    )
    answer_query_subgraph = answer_query_graph_builder().compile()
    graph.add_node(
        node="answer_query_subgraph",
        action=answer_query_subgraph,
    )

    base_raw_search_subgraph = base_raw_search_graph_builder().compile()
    graph.add_node(
        node="base_raw_search_subgraph",
        action=base_raw_search_subgraph,
    )

    # refined_answer_subgraph = refined_answers_graph_builder().compile()
    # graph.add_node(
    #     node="refined_answer_subgraph",
    #     action=refined_answer_subgraph,
    # )

    graph.add_node(
        node="refined_sub_question_creation",
        action=refined_sub_question_creation,
    )

    answer_refined_question = answer_refined_query_graph_builder().compile()
    graph.add_node(
        node="answer_refined_question",
        action=answer_refined_question,
    )

    graph.add_node(
        node="ingest_refined_answers",
        action=ingest_refined_answers,
    )

    graph.add_node(
        node="generate_refined_answer",
        action=generate_refined_answer,
    )

    # graph.add_node(
    #     node="check_refined_answer",
    #     action=check_refined_answer,
    # )

    graph.add_node(
        node="ingest_initial_retrieval",
        action=ingest_initial_base_retrieval,
    )

    graph.add_node(
        node="retrieval_consolidation",
        action=retrieval_consolidation,
    )

    graph.add_node(
        node="ingest_initial_sub_question_answers",
        action=ingest_initial_sub_question_answers,
    )
    graph.add_node(
        node="generate_initial_answer",
        action=generate_initial_answer,
    )

    graph.add_node(
        node="initial_answer_quality_check",
        action=initial_answer_quality_check,
    )

    graph.add_node(
        node="entity_term_extraction_llm",
        action=entity_term_extraction_llm,
    )
    graph.add_node(
        node="refined_answer_decision",
        action=refined_answer_decision,
    )

    graph.add_node(
        node="logging_node",
        action=agent_logging,
    )
    # if test_mode:
    #     graph.add_node(
    #         node="generate_initial_base_answer",
    #         action=generate_initial_base_answer,
    #     )

    ### Add edges ###

    # raph.add_edge(start_key=START, end_key="base_raw_search_subgraph")

    graph.add_edge(
        start_key=START,
        end_key="agent_path_decision",
    )

    graph.add_edge(
        start_key="agent_path_decision",
        end_key="agent_path_routing",
    )

    graph.add_edge(
        start_key="agent_search_start",
        end_key="base_raw_search_subgraph",
    )

    graph.add_edge(
        start_key="agent_search_start",
        end_key="initial_sub_question_creation",
    )

    graph.add_edge(
        start_key="base_raw_search_subgraph",
        end_key="ingest_initial_retrieval",
    )

    graph.add_edge(
        start_key=["ingest_initial_retrieval", "ingest_initial_sub_question_answers"],
        end_key="retrieval_consolidation",
    )

    graph.add_edge(
        start_key="retrieval_consolidation",
        end_key="entity_term_extraction_llm",
    )

    graph.add_edge(
        start_key="retrieval_consolidation",
        end_key="generate_initial_answer",
    )

    graph.add_edge(
        start_key="LLM",
        end_key=END,
    )

    # graph.add_edge(
    #     start_key=START,
    #     end_key="initial_sub_question_creation",
    # )

    graph.add_conditional_edges(
        source="initial_sub_question_creation",
        path=parallelize_initial_sub_question_answering,
        path_map=["answer_query_subgraph"],
    )
    graph.add_edge(
        start_key="answer_query_subgraph",
        end_key="ingest_initial_sub_question_answers",
    )

    graph.add_edge(
        start_key="retrieval_consolidation",
        end_key="generate_initial_answer",
    )

    # graph.add_edge(
    #     start_key="generate_initial_answer",
    #     end_key="entity_term_extraction_llm",
    # )

    graph.add_edge(
        start_key="generate_initial_answer",
        end_key="initial_answer_quality_check",
    )

    graph.add_edge(
        start_key=["initial_answer_quality_check", "entity_term_extraction_llm"],
        end_key="refined_answer_decision",
    )

    graph.add_conditional_edges(
        source="refined_answer_decision",
        path=continue_to_refined_answer_or_end,
        path_map=["refined_sub_question_creation", "logging_node"],
    )

    graph.add_conditional_edges(
        source="refined_sub_question_creation",  # DONE
        path=parallelize_refined_sub_question_answering,
        path_map=["answer_refined_question"],
    )
    graph.add_edge(
        start_key="answer_refined_question",  # HERE
        end_key="ingest_refined_answers",
    )

    graph.add_edge(
        start_key="ingest_refined_answers",
        end_key="generate_refined_answer",
    )

    # graph.add_conditional_edges(
    #     source="refined_answer_decision",
    #     path=continue_to_refined_answer_or_end,
    #     path_map=["refined_answer_subgraph", END],
    # )

    # graph.add_edge(
    #     start_key="refined_answer_subgraph",
    #     end_key="generate_refined_answer",
    # )

    graph.add_edge(
        start_key="generate_refined_answer",
        end_key="logging_node",
    )

    graph.add_edge(
        start_key="logging_node",
        end_key=END,
    )

    # graph.add_edge(
    #     start_key="generate_refined_answer",
    #     end_key="check_refined_answer",
    # )

    # graph.add_edge(
    #     start_key="check_refined_answer",
    #     end_key=END,
    # )

    return graph


if __name__ == "__main__":
    pass

    from onyx.db.engine import get_session_context_manager
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = main_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()

    with get_session_context_manager() as db_session:
        search_request = SearchRequest(query="Who created Excel?")
        agent_a_config, search_tool = get_test_config(
            db_session, primary_llm, fast_llm, search_request
        )

        inputs = MainInput(
            base_question=agent_a_config.search_request.query, log_messages=[]
        )

        for thing in compiled_graph.stream(
            input=inputs,
            config={"configurable": {"config": agent_a_config}},
            # stream_mode="debug",
            # debug=True,
            subgraphs=True,
        ):
            logger.debug(thing)
