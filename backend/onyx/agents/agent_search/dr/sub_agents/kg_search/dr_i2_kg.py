from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import DRPath
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import QuestionInputState
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.kb_search.states import MainInput as KbMainInput
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
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
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    search_query = state.question
    if not search_query:
        raise ValueError("search_query is not set")

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=(
                f"SUB-QUESTION {iteration_nr}.{parallelization_nr} "
                f"(KNOWLEDGE GRAPH): {search_query}\n\n"
            ),
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    logger.debug(f"Conducting a knowledge graph search for: {search_query}")

    kb_graph = kb_graph_builder().compile()

    kb_results = kb_graph.invoke(
        input=KbMainInput(question=search_query, individual_flow=False),
        config=config,
    )

    write_custom_event(
        "basic_response",
        AgentAnswerPiece(
            answer_piece=f"ANSWERED {iteration_nr}.{parallelization_nr}\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    # get cited documents
    answer_string = kb_results.get("final_answer") or "No answer provided"
    claims: list[str] = []
    retrieved_docs: list[InferenceSection] = kb_results.get("retrieved_documents", [])

    # add citations for the sql retrieved documents
    for i in range(len(retrieved_docs)):
        answer_string += f"[{i+1}]"

    (
        citation_numbers,
        answer_string,
        claims,
    ) = extract_document_citations(answer_string, claims)
    cited_documents = {
        citation_number: retrieved_docs[citation_number - 1]
        for citation_number in citation_numbers
    }

    return AnswerUpdate(
        iteration_responses=[
            IterationAnswer(
                tool=DRPath.KNOWLEDGE_GRAPH,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=search_query,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
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
