from datetime import datetime
from typing import Literal

from langgraph.types import Command

from onyx.agents.agent_search.deep_search_a.main.states import MainState


def agent_path_routing(
    state: MainState,
) -> Command[Literal["agent_search_start", "LLM"]]:
    now_start = datetime.now()
    routing = state.routing if hasattr(state, "routing") else "agent_search"

    if routing == "agent_search":
        agent_path = "agent_search_start"
    else:
        agent_path = "LLM"

    now_end = datetime.now()

    return Command(
        # state update
        update={
            "log_messages": [
                f"{now_end} -- Main - Path routing: {agent_path},  Time taken: {now_end - now_start}"
            ]
        },
        # control flow
        goto=agent_path,
    )
