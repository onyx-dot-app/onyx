from typing import Any
from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput


def prepare_tool_input(state: Any, config: RunnableConfig) -> ToolChoiceInput:
    agent_config = cast(GraphConfig, config["metadata"]["config"])
    return ToolChoiceInput(
        # NOTE: this node is used at the top level of the agent, so we always stream
        should_stream_answer=True,
        prompt_snapshot=None,  # uses default prompt builder
        tools=[tool.name for tool in (agent_config.tooling.tools or [])],
    )
