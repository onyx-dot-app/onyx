from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.kb_search.states import MainInput as KbMainInput
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.context.search.models import InferenceSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def kg_search(
    state: BranchInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> BranchUpdate:
    """
    LangGraph node to perform a KG search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    state.current_step_nr
    parallelization_nr = state.parallelization_nr

    search_query = state.branch_question
    if not search_query:
        raise ValueError("search_query is not set")

    logger.debug(
        f"Search start for KG Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    kg_tool_info = state.available_tools[state.tools_used[-1]]

    kb_graph = kb_graph_builder().compile()

    kb_results = kb_graph.invoke(
        input=KbMainInput(question=search_query, individual_flow=False),
        config=config,
    )

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

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=kg_tool_info.llm_path,
                tool_id=kg_tool_info.tool_id,
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
                graph_component="kg_search",
                node_name="searching",
                node_start_time=node_start_time,
            )
        ],
    )
