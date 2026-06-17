"""BuildStreamingState pure logic tests.

Tests for chunk accumulation and finalize semantics — no DB required.
"""

from __future__ import annotations

from typing import Any
from typing import cast
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.db.models import BuildSession
from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.session import streaming
from onyx.server.features.build.session.streaming import BuildStreamingState


class _FakeStreamingSandboxManager:
    supports_opencode_history_persistence = True

    def __init__(self) -> None:
        self.last_payload: dict[str, Any] | None = None
        self.resolved_opencode_session_id: str | None = None

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        user_message_content: str,
        *,
        opencode_session_id: str | None = None,
        agent_provider: str | None = None,
        agent_model: str | None = None,
        on_opencode_session_resolved: Any = None,  # noqa: ARG002
        should_interrupt: Any = None,  # noqa: ARG002
    ) -> Any:
        self.last_payload = {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "user_message_content": user_message_content,
            "opencode_session_id": opencode_session_id,
            "agent_provider": agent_provider,
            "agent_model": agent_model,
        }
        if on_opencode_session_resolved is not None:
            if self.resolved_opencode_session_id is not None:
                on_opencode_session_resolved(self.resolved_opencode_session_id)
        yield object()


class _FakePreflightSandboxManager:
    supports_opencode_history_persistence = True
    resolved_id = "ses_minted"

    def ensure_opencode_session(self, *_args: Any, **_kwargs: Any) -> str:
        return self.resolved_id


class _PreflightDb:
    commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1


class _FakeQuery:
    def __init__(self, build_session: BuildSession | None) -> None:
        self._build_session = build_session

    def filter(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def first(self) -> BuildSession | None:
        return self._build_session


class _FakePersistDb:
    def __init__(self, build_session: BuildSession | None) -> None:
        self.build_session = build_session
        self.commit_count = 0

    def query(self, _model: Any) -> _FakeQuery:
        return _FakeQuery(self.build_session)

    def commit(self) -> None:
        self.commit_count += 1


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

    def test_thought_chunks_persist_as_single_assistant_row(self) -> None:
        """Append two thought chunks -> finalize -> one synthetic packet."""
        state = BuildStreamingState(turn_index=0)

        state.add_thought_chunk("Thinking about ")
        state.add_thought_chunk("the problem...")

        packet = state.finalize_thought_chunks()

        assert packet is not None
        assert packet["type"] == "agent_thought"
        assert packet["content"]["text"] == "Thinking about the problem..."
        assert state.thought_chunks == []

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

    def test_routing_meta_change_finalizes_previous_chunk(self) -> None:
        """Parent and child chunks share packet types but must not share one
        persisted assistant row."""
        state = BuildStreamingState(turn_index=0)
        child_meta = {"sessionId": "child", "parentSessionId": "parent"}

        state.add_message_chunk("child text", child_meta)

        assert state.should_finalize_chunks("agent_message_chunk", child_meta) is False
        assert state.should_finalize_chunks("agent_message_chunk", None) is True

        packet = state.finalize_message_chunks()
        assert packet is not None
        assert packet["_meta"] == child_meta

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


def test_persist_sandbox_event_splits_chunks_by_routing_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted: list[dict[str, Any]] = []

    def create_message_stub(**kwargs: Any) -> None:
        persisted.append(cast(dict[str, Any], kwargs["message_metadata"]))

    monkeypatch.setattr(streaming, "create_message", create_message_stub)
    state = BuildStreamingState(turn_index=0)
    session_id = uuid4()
    child_meta = {"sessionId": "child", "parentSessionId": "parent"}

    parent_first = AgentMessageChunk.model_validate(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "parent first"},
        }
    )
    child = AgentMessageChunk.model_validate(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "child"},
            "_meta": child_meta,
        }
    )
    parent_second = AgentMessageChunk.model_validate(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "parent second"},
        }
    )

    streaming.persist_sandbox_event(
        cast(Any, object()), session_id, state, parent_first
    )
    streaming.persist_sandbox_event(cast(Any, object()), session_id, state, child)
    streaming.persist_sandbox_event(
        cast(Any, object()), session_id, state, parent_second
    )
    streaming.finalize_persist(cast(Any, object()), session_id, state)

    assert persisted == [
        {
            "type": "agent_message",
            "content": {"type": "text", "text": "parent first"},
            "sessionUpdate": "agent_message",
        },
        {
            "type": "agent_message",
            "content": {"type": "text", "text": "child"},
            "sessionUpdate": "agent_message",
            "_meta": child_meta,
        },
        {
            "type": "agent_message",
            "content": {"type": "text", "text": "parent second"},
            "sessionUpdate": "agent_message",
        },
    ]


def test_yield_sandbox_events_passes_existing_opencode_id() -> None:
    sandbox_manager = _FakeStreamingSandboxManager()
    sandbox_id = uuid4()
    session_id = uuid4()

    events = list(
        streaming.yield_sandbox_events(
            cast(Any, object()),
            cast(Any, sandbox_manager),
            sandbox_id,
            session_id,
            "continue",
            opencode_session_id="ses_existing",
            agent_provider=None,
            agent_model=None,
        )
    )

    assert len(events) == 1
    assert sandbox_manager.last_payload is not None
    assert sandbox_manager.last_payload["opencode_session_id"] == "ses_existing"


def test_yield_sandbox_events_persists_resolved_opencode_id() -> None:
    sandbox_manager = _FakeStreamingSandboxManager()
    sandbox_manager.resolved_opencode_session_id = "ses_fresh"
    session_id = uuid4()
    build_session = BuildSession(
        id=session_id,
        user_id=uuid4(),
        opencode_session_id="ses_stale",
    )
    db_session = _FakePersistDb(build_session)

    events = list(
        streaming.yield_sandbox_events(
            cast(Any, db_session),
            cast(Any, sandbox_manager),
            uuid4(),
            session_id,
            "continue",
            opencode_session_id="ses_stale",
            agent_provider=None,
            agent_model=None,
        )
    )

    assert len(events) == 1
    assert build_session.opencode_session_id == "ses_fresh"
    assert db_session.commit_count == 1


def test_yield_sandbox_events_passes_initial_opencode_id() -> None:
    sandbox_manager = _FakeStreamingSandboxManager()

    events = list(
        streaming.yield_sandbox_events(
            cast(Any, object()),
            cast(Any, sandbox_manager),
            uuid4(),
            uuid4(),
            "first prompt",
            opencode_session_id="ses_first_turn",
            agent_provider=None,
            agent_model=None,
        )
    )

    assert len(events) == 1
    assert sandbox_manager.last_payload is not None
    assert sandbox_manager.last_payload["opencode_session_id"] == "ses_first_turn"


def test_preflight_mints_opencode_id_when_missing() -> None:
    build_session = BuildSession(id=uuid4(), user_id=uuid4())
    db_session = _PreflightDb()

    resolved_id = streaming._ensure_opencode_session_id(
        cast(Any, db_session),
        cast(Any, _FakePreflightSandboxManager()),
        uuid4(),
        build_session,
    )

    assert resolved_id == "ses_minted"
    assert build_session.opencode_session_id == "ses_minted"
    assert db_session.commit_count == 1


def test_yield_sandbox_events_allows_non_empty_session_without_opencode_id() -> None:
    sandbox_manager = _FakeStreamingSandboxManager()

    events = list(
        streaming.yield_sandbox_events(
            cast(Any, object()),
            cast(Any, sandbox_manager),
            uuid4(),
            uuid4(),
            "continue",
            opencode_session_id=None,
            agent_provider=None,
            agent_model=None,
        )
    )

    assert len(events) == 1
    assert sandbox_manager.last_payload is not None
    assert sandbox_manager.last_payload["opencode_session_id"] is None
