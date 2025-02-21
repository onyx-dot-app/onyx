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


def format_initial_sub_answers(
    state: AnswerQuestionOutput,
) -> SubQuestionResultsUpdate:
    """
    LangGraph node to format the answers to the initial sub-questions, including
    deduping verified documents and context documents.
    """
    node_start_time = datetime.now()

    documents = []
    context_documents = []
    cited_documents = []
    answer_results = state.answer_results
    for answer_result in answer_results:
        documents.extend(answer_result.verified_reranked_documents)
        context_documents.extend(answer_result.context_documents)
        cited_documents.extend(answer_result.cited_documents)

    return SubQuestionResultsUpdate(
        # Deduping is done by the documents operator for the main graph
        # so we might not need to dedup here
        verified_reranked_documents=dedup_inference_sections(documents, []),
        context_documents=dedup_inference_sections(context_documents, []),
        cited_documents=dedup_inference_sections(cited_documents, []),
        sub_question_results=answer_results,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="initial - generate sub answers",
                node_name="format initial sub answers",
                node_start_time=node_start_time,
                result="",
            )
        ],
    )
