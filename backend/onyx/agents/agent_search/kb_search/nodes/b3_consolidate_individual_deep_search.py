from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.graph_utils import rename_entities_in_answer
from onyx.agents.agent_search.kb_search.graph_utils import stream_close_step_answer
from onyx.agents.agent_search.kb_search.graph_utils import (
    stream_write_step_answer_explicit,
)
from onyx.agents.agent_search.kb_search.states import ConsolidatedResearchUpdate
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.step_definitions import STEP_DESCRIPTIONS
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.models import SubQuestionAnswerResults
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def consolidate_individual_deep_search(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ConsolidatedResearchUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    _KG_STEP_NR = 4
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    graph_config.inputs.search_request.query
    state.entities_types_str

    research_object_results = state.research_object_results

    consolidated_research_object_results_str = "\n".join(
        [f"{x['object']}: {x['results']}" for x in research_object_results]
    )

    consolidated_research_object_results_str = rename_entities_in_answer(
        consolidated_research_object_results_str
    )

    step_answer = "All research is complete. Consolidating results..."

    stream_write_step_answer_explicit(
        writer, answer=step_answer, level=0, step_nr=_KG_STEP_NR
    )

    stream_close_step_answer(writer, level=0, step_nr=_KG_STEP_NR)

    return ConsolidatedResearchUpdate(
        consolidated_research_object_results_str=consolidated_research_object_results_str,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="generate simple sql",
                node_start_time=node_start_time,
            )
        ],
        step_results=[
            SubQuestionAnswerResults(
                question=STEP_DESCRIPTIONS[_KG_STEP_NR].description,
                question_id="0_" + str(_KG_STEP_NR),
                answer=step_answer,
                verified_high_quality=True,
                sub_query_retrieval_results=[],
                verified_reranked_documents=[],
                context_documents=[],
                cited_documents=[],
                sub_question_retrieval_stats=AgentChunkRetrievalStats(
                    verified_count=None,
                    verified_avg_scores=None,
                    rejected_count=None,
                    rejected_avg_scores=None,
                    verified_doc_chunk_ids=[],
                    dismissed_doc_chunk_ids=[],
                ),
            )
        ],
    )
