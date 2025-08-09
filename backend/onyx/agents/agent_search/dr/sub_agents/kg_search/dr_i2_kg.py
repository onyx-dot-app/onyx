from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import QuestionInputState
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.kb_search.states import MainInput as KbMainInput
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.context.search.models import InferenceSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def kg_query(
    state: QuestionInputState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> AnswerUpdate:
    """
    LangGraph node to perform a knowledge graph search as part of the DR process.
    """

    node_start_time = datetime.now()
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    search_query = state.question
    if not search_query:
        raise ValueError("search_query is not set")

    kg_tool_id = None
    for tool in graph_config.tooling.tools:
        if tool.name == "run_kg_search":
            kg_tool_id = tool.id
            break
    if kg_tool_id is None:
        raise ValueError("Knowledge graph tool id is not set. This should not happen.")

    # write_custom_event(
    #     "basic_response",
    #     AgentAnswerPiece(
    #         answer_piece=(
    #             f"SUB-QUESTION {iteration_nr}.{parallelization_nr} "
    #             f"(KNOWLEDGE GRAPH): {search_query}\n\n"
    #         ),
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    logger.debug(f"Conducting a knowledge graph search for: {search_query}")

    kb_graph = kb_graph_builder().compile()

    kb_results = kb_graph.invoke(
        input=KbMainInput(question=search_query, individual_flow=False),
        config=config,
    )

    # write_custom_event(
    #     "basic_response",
    #     AgentAnswerPiece(
    #         answer_piece=f"ANSWERED {iteration_nr}.{parallelization_nr}\n\n",
    #         level=0,
    #         level_question_num=0,
    #         answer_type="agent_level_answer",
    #     ),
    #     writer,
    # )

    # get cited documents
    answer_string = kb_results.get("final_answer") or "No answer provided"
    claims: list[str] = []
    retrieved_docs: list[InferenceSection] = kb_results.get("retrieved_documents", [])

    (
        citation_numbers,
        answer_string,
        claims,
    ) = extract_document_citations(answer_string, claims)

    # if citation is empty, the answer must have come from the KG rather than a doc
    # in that case, simply cite the docs returned by the KG
    if not citation_numbers:
        citation_numbers = [i + 1 for i in range(len(retrieved_docs))]

    cited_documents = {
        citation_number: retrieved_docs[citation_number - 1]
        for citation_number in citation_numbers
        if citation_number <= len(retrieved_docs)
    }

    return AnswerUpdate(
        iteration_responses=[
            IterationAnswer(
                tool=DRPath.KNOWLEDGE_GRAPH,
                tool_id=kg_tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=search_query,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
                reasoning=None,
                additional_data=None,
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
