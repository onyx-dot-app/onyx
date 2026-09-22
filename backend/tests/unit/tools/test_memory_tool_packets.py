"""Replay saved memory snapshots after native memory execution."""

from onyx.server.query_and_chat.session_loading import create_memory_packets
from onyx.server.query_and_chat.streaming_models import (
    MemoryToolDelta,
    MemoryToolStart,
    SectionEnd,
)


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
