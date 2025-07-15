from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.kb_search.states import MainInput as KbMainInput
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.utils.logger import setup_logger

logger = setup_logger()


def kg_query(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> AnswerUpdate:
    """
    LangGraph node to perform a knowledge graph search as part of the deep research process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    search_query = state.query_list[0]  # TODO: fix this

    logger.debug(f"Conducting a knowledge graph search for: {search_query}")

    kb_graph = kb_graph_builder().compile()

    # TODO: change this
    original_question = config["metadata"][
        "config"
    ].inputs.prompt_builder.raw_user_query
    kg_config = config.copy()
    kg_config["metadata"]["config"].behavior.use_agentic_search = True
    kg_config["metadata"]["config"].inputs.prompt_builder.raw_user_query = search_query

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=f"\n\nSUB-QUESTION (KNOWLEDGE GRAPH): {search_query}\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    kb_results = kb_graph.invoke(
        input=KbMainInput(individual_flow=False), config=kg_config
    )
    full_answer = kb_results.get("final_answer") or "No answer provided"

    config["metadata"][
        "config"
    ].inputs.prompt_builder.raw_user_query = original_question

    # create source document result list
    source_document_result_list = []
    for source_document in kb_results.get("source_documents", []):
        source_document_result_list.append(
            source_document,
        )

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece="\n\n-> answered!\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    return AnswerUpdate(
        answers=[kb_results.get("final_answer") or ""],
        iteration_responses=[
            IterationAnswer(
                iteration_nr=iteration_nr,
                parallelization_nr=0,
                question=search_query,
                answer=full_answer,
                cited_documents=kb_results.get(
                    "retrieved_documents", []
                ),  # TODO: add citations
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="kg search",
                node_start_time=node_start_time,
            )
        ],
    )
