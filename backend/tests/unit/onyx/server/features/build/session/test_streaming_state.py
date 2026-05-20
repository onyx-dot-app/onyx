"""BuildStreamingState pure logic tests.

Tests for chunk accumulation and finalize semantics — no DB required.
"""

from __future__ import annotations

from onyx.server.features.build.session.manager import BuildStreamingState


class TestBuildStreamingState:
    """Tests for BuildStreamingState class."""

    def test_message_chunks_accumulate(self) -> None:
        """Append two chunks → finalize → one synthetic packet with concatenated text."""
        state = BuildStreamingState(turn_index=0)

        state.add_message_chunk("Hello, ")
        state.add_message_chunk("world!")

        packet = state.finalize_message_chunks()

        assert packet is not None
        assert packet["type"] == "agent_message"
        assert packet["content"]["text"] == "Hello, world!"

        # After finalize, chunks should be cleared
        assert len(state.message_chunks) == 0

    def test_thought_chunks_accumulate_separately(self) -> None:
        """Message and thought chunks tracked independently."""
        state = BuildStreamingState(turn_index=0)

        state.add_thought_chunk("Thinking about ")
        state.add_thought_chunk("the problem...")

        packet = state.finalize_thought_chunks()

        assert packet is not None
        assert packet["type"] == "agent_thought"
        assert packet["content"]["text"] == "Thinking about the problem..."

    def test_type_change_finalizes_previous_type(self) -> None:
        """Driving the state machine through a real chunk → opposing-type packet should
        signal finalize. Same-type continuation should not.
        """
        # Case 1: message accumulation, then a thought event arrives → finalize True
        state = BuildStreamingState(turn_index=0)
        state.add_message_chunk("hello")
        assert state.should_finalize_chunks("agent_thought_chunk") is True

        # Case 2: same state, another message chunk arrives → no finalize
        assert state.should_finalize_chunks("agent_message_chunk") is False

        # Case 3 (inverse): fresh state, thought accumulation, then message arrives → finalize True
        state = BuildStreamingState(turn_index=0)
        state.add_thought_chunk("thinking")
        assert state.should_finalize_chunks("agent_message_chunk") is True

        # Case 4: continuing with another thought chunk → no finalize
        assert state.should_finalize_chunks("agent_thought_chunk") is False

    def test_finalize_with_no_chunks_is_noop(self) -> None:
        """Empty finalize returns None / does nothing."""
        state = BuildStreamingState(turn_index=0)

        assert state.finalize_message_chunks() is None
        assert state.finalize_thought_chunks() is None

    def test_clear_last_chunk_type_resets_boundary(self) -> None:
        """After clear, next chunk doesn't trigger spurious finalize.

        Sequence: add a message chunk (sets last_chunk_type='message'), call
        clear_last_chunk_type, then ask should_finalize_chunks for an event of
        a different type — it must return False because the boundary state has
        been wiped, even though chunks may still be buffered.
        """
        state = BuildStreamingState(turn_index=0)

        state.add_message_chunk("hello")
        # Sanity: without clear, a different event type would trigger finalize.
        assert state.should_finalize_chunks("agent_thought_chunk") is True

        state.clear_last_chunk_type()

        # After clearing the boundary tracker, no event type should trigger
        # a spurious finalize until a new chunk is accumulated.
        assert state.should_finalize_chunks("agent_thought_chunk") is False
        assert state.should_finalize_chunks("tool_call_progress") is False
        assert state.should_finalize_chunks("agent_message_chunk") is False

    def test_unknown_event_type_does_not_finalize(self) -> None:
        """Pins should_finalize_chunks behavior with no prior chunks.

        Per craft-risks.md §3.4 the state machine should not finalize when an
        unrecognised event type arrives outside of a chunk-accumulation
        burst — i.e. when ``_last_chunk_type`` is ``None``, an unknown event
        type must be a no-op rather than a spurious finalize.

        Note: when chunks ARE accumulating, the current implementation does
        trigger finalize on any non-matching type (including ``"unknown"``)
        because the predicate is ``new_packet_type != "agent_message_chunk"``.
        That is documented as ``subtle`` in craft-risks.md §3.4 and is left
        un-asserted here intentionally — pinning the no-prior-chunks case is
        the contract the rest of the streaming pipeline depends on.
        """
        state = BuildStreamingState(turn_index=0)

        # Without any prior chunk, unknown event types must NOT trigger finalize.
        assert state.should_finalize_chunks("unknown") is False
        assert state.should_finalize_chunks("some_future_event_type") is False
        assert state.should_finalize_chunks("agent_message_chunk") is False
        assert state.should_finalize_chunks("agent_thought_chunk") is False
