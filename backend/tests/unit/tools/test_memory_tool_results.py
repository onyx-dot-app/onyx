"""Memory results retain persisted text and operation identity."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.llm.cancellation import CancellationSignal
from onyx.tools.interface import ToolContext
from onyx.tools.models import MemoryUpdated
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool


@pytest.fixture
def progress() -> list[ToolProgress]:
    return []


@pytest.fixture
def invocation(progress: list[ToolProgress]) -> ToolInvocation:
    return ToolInvocation(
        call_id="memory",
        arguments={},
        cancellation=CancellationSignal(),
        update=progress.append,
    )


@pytest.fixture
def mock_llm() -> MagicMock:
    return MagicMock()


@pytest.fixture
def memory_tool(mock_llm: MagicMock, monkeypatch: pytest.MonkeyPatch) -> MemoryTool:
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.memory.memory_tool.add_memory",
        MagicMock(return_value=42),
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.memory.memory_tool.update_memory_at_index",
        MagicMock(return_value=42),
    )
    return MemoryTool(tool_id=1, llm=mock_llm)


@pytest.fixture
def tool_context() -> ToolContext:
    return ToolContext(
        user_memory_context=UserMemoryContext(
            user_id=uuid4(),
            user_info=UserInfo(name="Test User", email="test@example.com", role=None),
            memories=tuple(["User likes dark mode"]),
        )
    )


class TestMemoryToolRun:
    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_returns_add_operation(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        invocation: ToolInvocation,
        tool_context: ToolContext,
    ) -> None:
        mock_process.return_value = ("User prefers Python", None)

        invocation.arguments = {"memory": "User prefers Python"}
        result = memory_tool.run(invocation=invocation, context=tool_context)
        assert isinstance(result.details, MemoryUpdated)
        assert result.details.memory_text == "User prefers Python"
        assert result.details.operation == "add"
        assert result.details.memory_id == 42
        assert result.details.index is None

    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_returns_update_operation(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        invocation: ToolInvocation,
        tool_context: ToolContext,
    ) -> None:
        mock_process.return_value = ("User prefers light mode", 0)

        invocation.arguments = {"memory": "User prefers light mode"}
        result = memory_tool.run(invocation=invocation, context=tool_context)
        assert isinstance(result.details, MemoryUpdated)
        assert result.details.memory_text == "User prefers light mode"
        assert result.details.operation == "update"
        assert result.details.memory_id == 42
        assert result.details.index == 0
