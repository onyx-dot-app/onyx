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


def send_to_expanded_retrieval(state: SubQuestionAnsweringInput) -> Send | Hashable:
    """
    LangGraph edge to send a sub-question to the expanded retrieval.
    """
    edge_start_time = datetime.now()

    return Send(
        "initial_sub_question_expanded_retrieval",
        ExpandedRetrievalInput(
            question=state.question,
            base_search=False,
            sub_question_id=state.question_id,
            log_messages=[f"{edge_start_time} -- Sending to expanded retrieval"],
        ),
    )
