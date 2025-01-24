from datetime import datetime

from onyx.agents.agent_search.core_state import CoreState


def agent_search_start(state: CoreState) -> CoreState:
    now_end = datetime.now()
    return CoreState(log_messages=[f"{now_end} -- Main - Agent search start"])
