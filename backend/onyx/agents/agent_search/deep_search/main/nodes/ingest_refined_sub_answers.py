from datetime import datetime

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionOutput,
)
from onyx.agents.agent_search.deep_search.main.states import (
    SubQuestionResultsUpdate,
)
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)


def ingest_refined_sub_answers(
    state: AnswerQuestionOutput,
) -> SubQuestionResultsUpdate:
    """
    LangGraph node to ingest and format the refined sub-answers and retrieved documents.
    """
    node_start_time = datetime.now()

    documents = []
    answer_results = state.answer_results
    for answer_result in answer_results:
        documents.extend(answer_result.verified_reranked_documents)

    return SubQuestionResultsUpdate(
        # Deduping is done by the documents operator for the main graph
        # so we might not need to dedup here
        verified_reranked_documents=dedup_inference_sections(documents, []),
        sub_question_results=answer_results,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="ingest refined answers",
                node_start_time=node_start_time,
            )
        ],
    )
