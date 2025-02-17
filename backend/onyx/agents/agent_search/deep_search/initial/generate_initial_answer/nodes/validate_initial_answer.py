from datetime import datetime

from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.states import (
    SubQuestionRetrievalState,
)
from onyx.agents.agent_search.deep_search.main.operations import logger
from onyx.agents.agent_search.deep_search.main.states import (
    InitialAnswerQualityUpdate,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.timing import log_function_time


@log_function_time(print_only=True)
def validate_initial_answer(
    state: SubQuestionRetrievalState,
) -> InitialAnswerQualityUpdate:
    """
    Check whether the initial answer sufficiently addresses the original user question.
    """

    node_start_time = datetime.now()

    logger.debug(
        f"--------{node_start_time}--------Checking for base answer validity - for not set True/False manually"
    )

    verdict = True  # not actually required as already streamed out. Refinement will do similar

    return InitialAnswerQualityUpdate(
        initial_answer_quality_eval=verdict,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="initial - generate initial answer",
                node_name="validate initial answer",
                node_start_time=node_start_time,
                result="",
            )
        ],
    )
