from collections.abc import Hashable
from datetime import datetime

from langgraph.types import Send

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    SubQuestionAnsweringInput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def send_to_expanded_refined_retrieval(
    state: SubQuestionAnsweringInput,
) -> Send | Hashable:
    """
    LangGraph edge to sends a refined sub-question extended retrieval.
    """
    logger.debug("sending to expanded retrieval for follow up question via edge")
    datetime.now()
    return Send(
        "refined_sub_question_expanded_retrieval",
        ExpandedRetrievalInput(
            question=state.question,
            sub_question_id=state.question_id,
            base_search=False,
            log_messages=[f"{datetime.now()} -- Sending to expanded retrieval"],
        ),
    )
