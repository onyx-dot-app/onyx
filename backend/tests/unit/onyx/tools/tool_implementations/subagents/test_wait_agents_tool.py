from unittest.mock import MagicMock

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.subagents.subagent_tools import WaitAgentsTool


def test_wait_agents_refuses_while_a_code_cell_is_open() -> None:
    """Ending the response would stop the open cell."""
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = {}

    with pytest.raises(ToolCallException, match="code cell"):
        WaitAgentsTool(has_open_cells=lambda: True)._run(invocation, MagicMock())

    invocation.agents.discover_agents.assert_not_called()
