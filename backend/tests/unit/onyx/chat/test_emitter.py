"""Unit tests for the Emitter class.

All tests use the streaming mode (merged_queue required). Emitter has a single
code path — no standalone bus.
"""

import queue

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningStart

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _placement(
    turn_index: int = 0,
    tab_index: int = 0,
    sub_turn_index: int | None = None,
) -> Placement:
    return Placement(
        turn_index=turn_index,
        tab_index=tab_index,
        sub_turn_index=sub_turn_index,
    )


def _packet(
    turn_index: int = 0,
    tab_index: int = 0,
    sub_turn_index: int | None = None,
) -> Packet:
    """Build a minimal valid packet with an OverallStop payload."""
    return Packet(
        placement=_placement(turn_index, tab_index, sub_turn_index),
        obj=OverallStop(stop_reason="test"),
    )


def _make_emitter(model_idx: int = 0) -> tuple["Emitter", "queue.Queue"]:
    """Return (emitter, queue) wired together."""
    mq: queue.Queue = queue.Queue()
    return Emitter(merged_queue=mq, model_idx=model_idx), mq


# ---------------------------------------------------------------------------
# Queue routing
# ---------------------------------------------------------------------------


class TestEmitterQueueRouting:
    def test_emit_lands_on_merged_queue(self) -> None:
        emitter, mq = _make_emitter()
        emitter.emit(_packet())
        assert not mq.empty()

    def test_queue_item_is_tuple_of_key_and_packet(self) -> None:
        emitter, mq = _make_emitter(model_idx=1)
        emitter.emit(_packet())
        item = mq.get_nowait()
        assert isinstance(item, tuple)
        assert len(item) == 2

    def test_multiple_packets_delivered_fifo(self) -> None:
        emitter, mq = _make_emitter()
        p1 = _packet(turn_index=0)
        p2 = _packet(turn_index=1)
        emitter.emit(p1)
        emitter.emit(p2)
        _, t1 = mq.get_nowait()
        _, t2 = mq.get_nowait()
        assert t1.placement.turn_index == 0
        assert t2.placement.turn_index == 1


# ---------------------------------------------------------------------------
# model_index tagging
# ---------------------------------------------------------------------------


class TestEmitterModelIndexTagging:
    def test_n1_default_model_idx_tags_model_index_zero(self) -> None:
        """N=1: default model_idx=0, so packet gets model_index=0."""
        emitter, mq = _make_emitter(model_idx=0)
        emitter.emit(_packet())
        _key, tagged = mq.get_nowait()
        assert tagged.placement.model_index == 0

    def test_model_idx_one_tags_packet(self) -> None:
        emitter, mq = _make_emitter(model_idx=1)
        emitter.emit(_packet())
        _key, tagged = mq.get_nowait()
        assert tagged.placement.model_index == 1

    def test_model_idx_two_tags_packet(self) -> None:
        """Boundary: third model in a 3-model run."""
        emitter, mq = _make_emitter(model_idx=2)
        emitter.emit(_packet())
        _key, tagged = mq.get_nowait()
        assert tagged.placement.model_index == 2


# ---------------------------------------------------------------------------
# Queue key
# ---------------------------------------------------------------------------


class TestEmitterQueueKey:
    def test_key_equals_model_idx(self) -> None:
        """Drain loop uses the key to route packets; it must match model_idx."""
        emitter, mq = _make_emitter(model_idx=2)
        emitter.emit(_packet())
        key, _ = mq.get_nowait()
        assert key == 2

    def test_n1_key_is_zero(self) -> None:
        emitter, mq = _make_emitter(model_idx=0)
        emitter.emit(_packet())
        key, _ = mq.get_nowait()
        assert key == 0


# ---------------------------------------------------------------------------
# Placement field preservation
# ---------------------------------------------------------------------------


class TestEmitterPlacementPreservation:
    def test_turn_index_is_preserved(self) -> None:
        emitter, mq = _make_emitter()
        emitter.emit(_packet(turn_index=5))
        _, tagged = mq.get_nowait()
        assert tagged.placement.turn_index == 5

    def test_tab_index_is_preserved(self) -> None:
        emitter, mq = _make_emitter()
        emitter.emit(_packet(tab_index=3))
        _, tagged = mq.get_nowait()
        assert tagged.placement.tab_index == 3

    def test_sub_turn_index_is_preserved(self) -> None:
        emitter, mq = _make_emitter()
        emitter.emit(_packet(sub_turn_index=2))
        _, tagged = mq.get_nowait()
        assert tagged.placement.sub_turn_index == 2

    def test_sub_turn_index_none_is_preserved(self) -> None:
        emitter, mq = _make_emitter()
        emitter.emit(_packet(sub_turn_index=None))
        _, tagged = mq.get_nowait()
        assert tagged.placement.sub_turn_index is None

    def test_packet_obj_is_not_modified(self) -> None:
        """The payload object must survive tagging untouched."""
        emitter, mq = _make_emitter()
        original_obj = OverallStop(stop_reason="sentinel")
        pkt = Packet(placement=_placement(), obj=original_obj)
        emitter.emit(pkt)
        _, tagged = mq.get_nowait()
        assert tagged.obj is original_obj

    def test_different_obj_types_are_handled(self) -> None:
        """Any valid PacketObj type passes through correctly."""
        emitter, mq = _make_emitter()
        pkt = Packet(placement=_placement(), obj=ReasoningStart())
        emitter.emit(pkt)
        _, tagged = mq.get_nowait()
        assert isinstance(tagged.obj, ReasoningStart)
