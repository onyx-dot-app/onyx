from datetime import datetime

from onyx.agents.agent_search.deep_search_a.main.states import LoggerUpdate
from onyx.agents.agent_search.deep_search_a.main.states import MainState


def retrieval_consolidation(
    state: MainState,
) -> LoggerUpdate:
    now_start = datetime.now()

    return LoggerUpdate(log_messages=[f"{now_start} -- Retrieval consolidation"])
