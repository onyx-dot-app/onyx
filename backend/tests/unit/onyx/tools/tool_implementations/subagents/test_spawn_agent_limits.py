from unittest.mock import MagicMock

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.db.chat_inputs import MAX_PENDING_MESSAGE_BYTES
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.subagents.subagent_tools import (
    MAX_AGENT_NAME_BYTES,
    SpawnAgentTool,
)


@pytest.mark.parametrize(
    "arguments",
    [
        # Each character takes two bytes, so the text is under the limit in characters.
        {"name": "é" * (MAX_AGENT_NAME_BYTES // 2 + 1), "instruction": "Research."},
        {"name": "research", "instruction": "é" * (MAX_PENDING_MESSAGE_BYTES // 2 + 1)},
    ],
    ids=["name", "instruction"],
)
def test_spawn_rejects_oversized_input_before_starting_a_child(
    arguments: dict[str, str],
) -> None:
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = arguments
    create_agent = MagicMock()
    tool = SpawnAgentTool(create_agent, max_steps=3)

    with pytest.raises(ToolCallException, match="bytes"):
        tool._run(invocation, MagicMock())

    create_agent.assert_not_called()
    invocation.agents.spawn_agent.assert_not_called()
