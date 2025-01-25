from datetime import datetime

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import (
    InitialAnswerQualityUpdate,
)
from onyx.agents.agent_search.deep_search_a.main.states import MainState


def initial_answer_quality_check(state: MainState) -> InitialAnswerQualityUpdate:
    """
    Check whether the final output satisfies the original user question

    Args:
        state (messages): The current state

    Returns:
        InitialAnswerQualityUpdate
    """

    now_start = datetime.now()

    logger.debug(
        f"--------{now_start}--------Checking for base answer validity - for not set True/False manually"
    )

    verdict = True

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL ANSWER QUALITY CHECK END---"
    )

    return InitialAnswerQualityUpdate(
        initial_answer_quality=verdict,
        log_messages=[
            f"{now_end} -- Main - Initial answer quality check,  Time taken: {now_end - now_start}"
        ],
    )
