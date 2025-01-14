from collections.abc import Hashable

from langgraph.types import Send

from onyx.agent_search.core_state import in_subgraph_extract_core_fields
from onyx.agent_search.pro_search_a.answer_initial_sub_question.states import (
    AnswerQuestionInput,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def send_to_expanded_retrieval(state: AnswerQuestionInput) -> Send | Hashable:
    logger.debug("sending to expanded retrieval via edge")

    return Send(
        "initial_sub_question_expanded_retrieval",
        ExpandedRetrievalInput(
            **in_subgraph_extract_core_fields(state),
            question=state["question"],
            base_search=False,
            sub_question_id=state["question_id"],
        ),
    )
