"""Unit tests for CodingAgentTool.

Coverage is intentionally narrow — the heavy lifting lives in
``run_coding_agent_call`` and ``BashTool``, both tested separately. This
file exists to lock in the wiring this Tool wrapper is responsible for.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)


def test_is_available_delegates_to_bash_tool() -> None:
    """CodingAgentTool can't function without BashTool, so its availability
    must be a strict subset. Delegation keeps the env / DB / health /
    version-gate checks in one place instead of drifting between two
    implementations."""
    db_session = MagicMock()

    with patch(
        "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
        ".BashTool.is_available",
        return_value=True,
    ) as mock_is_available:
        assert CodingAgentTool.is_available(db_session) is True
        mock_is_available.assert_called_once_with(db_session)


def test_is_available_false_when_bash_tool_unavailable() -> None:
    db_session = MagicMock()

    with patch(
        "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
        ".BashTool.is_available",
        return_value=False,
    ):
        assert CodingAgentTool.is_available(db_session) is False
