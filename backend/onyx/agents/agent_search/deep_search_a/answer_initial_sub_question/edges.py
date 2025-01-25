from collections.abc import Hashable
from datetime import datetime

from langgraph.types import Send

from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionInput,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def send_to_expanded_retrieval(state: AnswerQuestionInput) -> Send | Hashable:
    logger.debug("sending to expanded retrieval via edge")
    now_start = datetime.now()

    return Send(
        "initial_sub_question_expanded_retrieval",
        ExpandedRetrievalInput(
            question=state.question,
            base_search=False,
            sub_question_id=state.question_id,
            log_messages=[f"{now_start} -- Sending to expanded retrieval"],
        ),
    )
