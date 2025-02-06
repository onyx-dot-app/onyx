from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionOutput,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.shared_graph_utils.models import (
    SubQuestionAnswerResults,
)


def format_sub_answer(state: AnswerQuestionState) -> AnswerQuestionOutput:
    """
    LangGraph node to generate the sub-answer format.
    """
    return AnswerQuestionOutput(
        answer_results=[
            SubQuestionAnswerResults(
                question=state.question,
                question_id=state.question_id,
                verified_high_quality=state.answer_quality,
                answer=state.answer,
                sub_query_retrieval_results=state.expanded_retrieval_results,
                verified_reranked_documents=state.verified_reranked_documents,
                context_documents=state.context_documents,
                cited_documents=state.cited_documents,
                sub_question_retrieval_stats=state.sub_question_retrieval_stats,
            )
        ],
    )
