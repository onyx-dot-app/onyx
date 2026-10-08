"""Memory results retain persisted text and operation identity."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.chat.renderer import ToolRenderer
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolCall, ToolResult
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    MemoryToolDelta,
    MemoryToolStart,
    SectionEnd,
    ToolCallDebug,
)
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
            memories=("User likes dark mode",),
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
        assert isinstance(result, ToolResult)
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
        assert isinstance(result, ToolResult)
        assert isinstance(result.details, MemoryUpdated)
        assert result.details.memory_text == "User prefers light mode"
        assert result.details.operation == "update"
        assert result.details.memory_id == 42
        assert result.details.index == 0

        placement = Placement(turn_index=5, tab_index=2)
        renderer = ToolRenderer(
            ToolCall(
                id=invocation.call_id,
                name=memory_tool.name,
                arguments=invocation.arguments,
            ),
            placement,
        )
        packets = [
            packet
            for packet in renderer.start() + renderer.complete(result)
            if not isinstance(packet.obj, ToolCallDebug)
        ]
        assert [type(packet.obj) for packet in packets] == [
            MemoryToolStart,
            MemoryToolDelta,
            SectionEnd,
        ]
        assert all(packet.placement == placement for packet in packets)
        delta = packets[1].obj
        assert isinstance(delta, MemoryToolDelta)
        assert (delta.memory_text, delta.operation, delta.memory_id, delta.index) == (
            "User prefers light mode",
            "update",
            42,
            0,
        )
