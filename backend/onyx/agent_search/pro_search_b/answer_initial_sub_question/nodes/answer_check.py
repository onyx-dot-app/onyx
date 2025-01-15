from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    AnswerQuestionState,
)
from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    QACheckUpdate,
)


def answer_check(state: AnswerQuestionState) -> QACheckUpdate:
    quality_str = "yes"

    return QACheckUpdate(
        answer_quality=quality_str,
    )
