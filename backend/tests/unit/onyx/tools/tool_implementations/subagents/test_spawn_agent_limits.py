from unittest.mock import MagicMock

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.db.chat_inputs import MAX_PENDING_MESSAGE_BYTES
from onyx.llm.model_capabilities import ToolFamily
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.subagents.shapes import (
    AGENT_SHAPES,
)
from onyx.tools.tool_implementations.subagents.subagent_tools import (
    MAX_AGENT_NAME_BYTES,
    SpawnAgentTool,
)

# Each character takes two bytes, so the text is under the limit in characters.
_LONG_NAME = "é" * (MAX_AGENT_NAME_BYTES // 2 + 1)
_LONG_TASK = "é" * (MAX_PENDING_MESSAGE_BYTES // 2 + 1)


@pytest.mark.parametrize(
    ("family", "arguments", "field"),
    [
        (
            ToolFamily.OPENAI,
            {"task_name": _LONG_NAME, "message": "Research."},
            "task_name",
        ),
        (
            ToolFamily.OPENAI,
            {"task_name": "research", "message": _LONG_TASK},
            "message",
        ),
        (
            ToolFamily.CLAUDE,
            {"description": _LONG_NAME, "prompt": "Research."},
            "description",
        ),
        (
            ToolFamily.CLAUDE,
            {"description": "research", "prompt": _LONG_TASK},
            "prompt",
        ),
    ],
)
def test_spawn_rejects_oversized_input_before_starting_a_child(
    family: ToolFamily, arguments: dict[str, str], field: str
) -> None:
    """The error names the argument as the model's shape calls it."""
    invocation = MagicMock(spec=ToolInvocation)
    invocation.arguments = arguments
    create_agent = MagicMock()
    tool = SpawnAgentTool(create_agent, AGENT_SHAPES[family], max_steps=3)

    with pytest.raises(ToolCallException) as error:
        tool._run(invocation, MagicMock())

    assert error.value.llm_facing_message.startswith(f"The {field} can have at most")
    assert error.value.llm_facing_message.endswith(f"call {tool.name} again.")
    create_agent.assert_not_called()
    invocation.agents.spawn_agent.assert_not_called()
