from typing import Literal

from langgraph.types import Command

from onyx.agents.agent_search.deep_search_a.main.states import MainState


def agent_path_routing(
    state: MainState,
) -> Command[Literal["agent_search_start", "LLM"]]:
    routing = state.routing if hasattr(state, "routing") else "agent_search"

    if routing == "agent_search":
        agent_path = "agent_search_start"
    else:
        agent_path = "LLM"

    return Command(
        # state update
        update={"log_messages": [f"Path routing: {agent_path}"]},
        # control flow
        goto=agent_path,
    )
