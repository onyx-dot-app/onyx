from unittest.mock import MagicMock

import pytest

from onyx.agents.models import AgentInfo, RunStatus
from onyx.agents.tools import ToolInvocation
from onyx.llm.model_capabilities import ToolFamily
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.subagents.models import (
    AgentWaitDetails,
)
from onyx.tools.tool_implementations.subagents.shapes import AGENT_SHAPES
from onyx.tools.tool_implementations.subagents.subagent_tools import WaitAgentTool


def test_wait_agent_refuses_while_a_code_cell_is_open() -> None:
    """Ending the response would stop the open cell."""
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = {}

    with pytest.raises(ToolCallException) as raised:
        WaitAgentTool(
            AGENT_SHAPES[ToolFamily.OPENAI], open_cell_wait_name=lambda: "poll"
        )._run(invocation, MagicMock())
    assert raised.value.llm_facing_message == (
        "A code cell is still open, and ending your response would stop it. "
        "Wait for it with poll first."
    )


def test_an_empty_agent_list_waits_for_all_agents() -> None:
    """The saved wait holds the same agents that the call reports."""
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = {"targets": []}
    invocation.agents.agent_id = "root"
    invocation.agents.discover_agents.return_value = [
        AgentInfo(
            id=name,
            path=f"/root/{name}",
            parent_id="root",
            description="",
            restoration_config=None,
            status=RunStatus.RUNNING,
        )
        for name in ("alpha", "beta")
    ]

    result = WaitAgentTool(
        AGENT_SHAPES[ToolFamily.OPENAI], open_cell_wait_name=lambda: None
    )._run(invocation, MagicMock())

    assert result.content == "Waiting for 2 agents: /root/alpha, /root/beta."
    assert result.details == AgentWaitDetails(agent_ids=None)
    assert result.terminate
