"""Tests for memory tool streaming packet emissions."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.llm.cancellation import CancellationSignal
from onyx.server.query_and_chat.session_loading import create_memory_packets
from onyx.server.query_and_chat.streaming_models import (
    MemoryToolDelta,
    MemoryToolStart,
    SectionEnd,
)
from onyx.tools.interface import ToolContext
from onyx.tools.progress import MemoryOperation, MemoryUpdated
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
    def test_run_emits_delta_for_add_operation(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        progress: list[ToolProgress],
        invocation: ToolInvocation,
        tool_context: ToolContext,
    ) -> None:
        mock_process.return_value = ("User prefers Python", None)

        invocation.arguments = {"memory": "User prefers Python"}
        memory_tool.run(invocation=invocation, context=tool_context)

        packet = next(
            item for item in progress if isinstance(item.details, MemoryUpdated)
        )
        assert isinstance(packet.details, MemoryUpdated)
        assert packet.details.memory_text == "User prefers Python"
        assert packet.details.operation == "add"
        assert packet.details.memory_id == 42
        assert packet.details.index is None

    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_emits_delta_for_update_operation(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        progress: list[ToolProgress],
        invocation: ToolInvocation,
        tool_context: ToolContext,
    ) -> None:
        mock_process.return_value = ("User prefers light mode", 0)

        invocation.arguments = {"memory": "User prefers light mode"}
        memory_tool.run(invocation=invocation, context=tool_context)

        packet = next(
            item for item in progress if isinstance(item.details, MemoryUpdated)
        )
        assert isinstance(packet.details, MemoryUpdated)
        assert packet.details.memory_text == "User prefers light mode"
        assert packet.details.operation == "update"
        assert packet.details.memory_id == 42
        assert packet.details.index == 0

    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_returns_saved_memory(
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
        assert result.details.index is None
        assert "User prefers Python" in result.text


class TestCreateMemoryPackets:
    def test_produces_start_delta_end_for_add(self) -> None:
        packets = create_memory_packets(
            memory_text="User likes Python",
            operation=MemoryOperation.ADD,
            memory_id=None,
            turn_index=1,
            tab_index=0,
        )

        assert len(packets) == 3
        assert isinstance(packets[0].obj, MemoryToolStart)
        assert isinstance(packets[1].obj, MemoryToolDelta)
        assert isinstance(packets[2].obj, SectionEnd)

        delta = packets[1].obj
        assert isinstance(delta, MemoryToolDelta)
        assert delta.memory_text == "User likes Python"
        assert delta.operation == "add"
        assert delta.memory_id is None
        assert delta.index is None

    def test_produces_start_delta_end_for_update(self) -> None:
        packets = create_memory_packets(
            memory_text="User prefers light mode",
            operation=MemoryOperation.UPDATE,
            memory_id=42,
            turn_index=3,
            tab_index=1,
            index=5,
        )

        assert len(packets) == 3
        assert isinstance(packets[0].obj, MemoryToolStart)
        assert isinstance(packets[1].obj, MemoryToolDelta)
        assert isinstance(packets[2].obj, SectionEnd)

        delta = packets[1].obj
        assert isinstance(delta, MemoryToolDelta)
        assert delta.memory_text == "User prefers light mode"
        assert delta.operation == "update"
        assert delta.memory_id == 42
        assert delta.index == 5

    def test_placement_is_set_correctly(self) -> None:
        packets = create_memory_packets(
            memory_text="test",
            operation=MemoryOperation.ADD,
            memory_id=None,
            turn_index=5,
            tab_index=2,
        )

        for packet in packets:
            assert packet.placement.turn_index == 5
            assert packet.placement.tab_index == 2
