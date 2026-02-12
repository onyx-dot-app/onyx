"""Tests for memory tool streaming packet emissions."""

from queue import Queue
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import create_memory_packets
from onyx.server.query_and_chat.streaming_models import MemoryToolDelta
from onyx.server.query_and_chat.streaming_models import MemoryToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.memory.memory_tool import MemoryToolOverrideKwargs
from onyx.tools.tool_implementations.memory.models import MemoryToolResponse


@pytest.fixture
def emitter() -> Emitter:
    bus: Queue = Queue()
    return Emitter(bus)


@pytest.fixture
def mock_llm() -> MagicMock:
    return MagicMock()


@pytest.fixture
def memory_tool(emitter: Emitter, mock_llm: MagicMock) -> MemoryTool:
    return MemoryTool(tool_id=1, emitter=emitter, llm=mock_llm)


@pytest.fixture
def placement() -> Placement:
    return Placement(turn_index=0, tab_index=0)


@pytest.fixture
def override_kwargs() -> MemoryToolOverrideKwargs:
    return MemoryToolOverrideKwargs(
        user_name="Test User",
        user_email="test@example.com",
        user_role=None,
        existing_memories=["User likes dark mode"],
        chat_history=[],
    )


class TestMemoryToolEmitStart:
    def test_emit_start_emits_memory_tool_start_packet(
        self,
        memory_tool: MemoryTool,
        emitter: Emitter,
        placement: Placement,
    ) -> None:
        memory_tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, MemoryToolStart)
        assert packet.placement == placement

    def test_emit_start_with_different_placement(
        self,
        memory_tool: MemoryTool,
        emitter: Emitter,
    ) -> None:
        placement = Placement(turn_index=2, tab_index=1)
        memory_tool.emit_start(placement)

        packet = emitter.bus.get_nowait()
        assert packet.placement.turn_index == 2
        assert packet.placement.tab_index == 1


class TestMemoryToolRun:
    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_emits_delta_for_add_operation(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        emitter: Emitter,
        placement: Placement,
        override_kwargs: MemoryToolOverrideKwargs,
    ) -> None:
        mock_process.return_value = ("User prefers Python", None)

        memory_tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            memory="User prefers Python",
        )

        # The delta packet should be in the queue
        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, MemoryToolDelta)
        assert packet.obj.memory_text == "User prefers Python"
        assert packet.obj.operation == "add"
        assert packet.obj.memory_id is None
        assert packet.obj.index is None
        assert packet.placement == placement

    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_emits_delta_for_update_operation(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        emitter: Emitter,
        placement: Placement,
        override_kwargs: MemoryToolOverrideKwargs,
    ) -> None:
        mock_process.return_value = ("User prefers light mode", 0)

        memory_tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            memory="User prefers light mode",
        )

        packet = emitter.bus.get_nowait()
        assert isinstance(packet.obj, MemoryToolDelta)
        assert packet.obj.memory_text == "User prefers light mode"
        assert packet.obj.operation == "update"
        assert packet.obj.memory_id is None
        assert packet.obj.index == 0

    @patch("onyx.tools.tool_implementations.memory.memory_tool.process_memory_update")
    def test_run_returns_tool_response_with_rich_response(
        self,
        mock_process: MagicMock,
        memory_tool: MemoryTool,
        placement: Placement,
        override_kwargs: MemoryToolOverrideKwargs,
    ) -> None:
        mock_process.return_value = ("User prefers Python", None)

        result = memory_tool.run(
            placement=placement,
            override_kwargs=override_kwargs,
            memory="User prefers Python",
        )

        assert isinstance(result.rich_response, MemoryToolResponse)
        assert result.rich_response.memory_text == "User prefers Python"
        assert result.rich_response.index_to_replace is None
        assert "User prefers Python" in result.llm_facing_response


class TestCreateMemoryPackets:
    def test_produces_start_delta_end_for_add(self) -> None:
        packets = create_memory_packets(
            memory_text="User likes Python",
            operation="add",
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
            operation="update",
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
            operation="add",
            memory_id=None,
            turn_index=5,
            tab_index=2,
        )

        for packet in packets:
            assert packet.placement.turn_index == 5
            assert packet.placement.tab_index == 2
