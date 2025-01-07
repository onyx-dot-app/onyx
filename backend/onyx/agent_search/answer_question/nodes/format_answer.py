from onyx.agent_search.answer_question.states import AnswerQuestionOutput
from onyx.agent_search.answer_question.states import AnswerQuestionState
from onyx.agent_search.answer_question.states import QuestionAnswerResults


def format_answer(state: AnswerQuestionState) -> AnswerQuestionOutput:
    return AnswerQuestionOutput(
        answer_results=[
            QuestionAnswerResults(
                question=state["question"],
                question_id=state["question_id"],
                quality=state.get("answer_quality", "No"),
                answer=state["answer"],
                expanded_retrieval_results=state["expanded_retrieval_results"],
                documents=state["documents"],
                sub_question_retrieval_stats=state["sub_question_retrieval_stats"],
            )
        ],
    )
