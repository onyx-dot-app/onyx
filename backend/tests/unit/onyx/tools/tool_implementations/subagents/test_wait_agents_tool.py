from unittest.mock import MagicMock

import pytest

from onyx.agents.models import AgentInfo, RunStatus
from onyx.agents.tools import ToolInvocation
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.subagents.models import AgentWaitDetails
from onyx.tools.tool_implementations.subagents.subagent_tools import WaitAgentsTool


def test_wait_agents_refuses_while_a_code_cell_is_open() -> None:
    """Ending the response would stop the open cell."""
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = {}

    with pytest.raises(ToolCallException, match="code cell"):
        WaitAgentsTool(has_open_cells=lambda: True)._run(invocation, MagicMock())


def test_an_empty_agent_list_waits_for_all_agents() -> None:
    """The saved wait holds the same agents that the call reports."""
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = {"agent_ids": []}
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

    result = WaitAgentsTool(has_open_cells=lambda: False)._run(invocation, MagicMock())

    assert result.content == "Waiting for 2 agents: /root/alpha, /root/beta."
    assert result.details == AgentWaitDetails(agent_ids=None)
    assert result.terminate
