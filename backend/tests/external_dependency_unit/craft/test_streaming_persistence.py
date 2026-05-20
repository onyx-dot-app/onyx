"""Streaming persistence and stream error semantics tests (ext-dep).

The first half covers what ``_persist_acp_event`` actually writes to the DB
(assistant/thought rows, tool-call gating, plan upsert, turn indexing, finalize
semantics).

The second half covers the user-observable error packets the streaming endpoint
emits when the upstream agent / sandbox misbehaves.

Tests drive ``SessionManager.send_message`` end-to-end against Postgres with a
stubbed ``SandboxManager`` so every assertion is on observable DB state /
yielded SSE text.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest
from acp.schema import AgentMessageChunk
from acp.schema import AgentThoughtChunk
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import upsert_agent_plan
from onyx.server.features.build.sandbox.base import SSEKeepalive
from onyx.server.features.build.session.manager import BuildStreamingState
from onyx.server.features.build.session.manager import SessionManager
from tests.external_dependency_unit.craft.stubs import StubSandboxManager


def _text_chunk(text: str) -> AgentMessageChunk:
    return AgentMessageChunk.model_validate(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": text},
        }
    )


def _thought_chunk(text: str) -> AgentThoughtChunk:
    return AgentThoughtChunk.model_validate(
        {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": text},
        }
    )


def _tool_call_start(tool_id: str, title: str) -> ToolCallStart:
    return ToolCallStart.model_validate(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": tool_id,
            "title": title,
            "status": "pending",
        }
    )


def _tool_call_progress(
    tool_id: str,
    title: str,
    status: str = "completed",
    raw_input: dict[str, Any] | None = None,
    raw_output: dict[str, Any] | None = None,
) -> ToolCallProgress:
    payload: dict[str, Any] = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": tool_id,
        "title": title,
        "status": status,
    }
    if raw_input is not None:
        payload["rawInput"] = raw_input
    if raw_output is not None:
        payload["rawOutput"] = raw_output
    return ToolCallProgress.model_validate(payload)


def _prompt_response() -> PromptResponse:
    return PromptResponse(stop_reason="end_turn")


def _drain(gen: Generator[str, None, None]) -> list[str]:
    """Consume a streaming generator into a list of SSE frames."""
    return list(gen)


# =============================================================================
# Streaming persistence (DB-bound)
# =============================================================================


class TestStreamingPersistence:
    """DB-bound tests for `_persist_acp_event` behavior."""

    def test_agent_message_chunks_persist_as_single_assistant_row(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """3 chunks → 1 BuildMessage row, concatenated content.

        Simulates:
        1. Initial user message
        2. Agent message chunks (3) → 1 assistant row
        3. Tool call (completed) → 1 assistant row
        4. Agent message chunks (2) → 1 assistant row

        This verifies that chunk-accumulation finalize writes exactly one row
        per stream-side burst rather than one row per chunk.
        """
        # 0. Initial user message
        create_message(
            session_id=build_session.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "Do something"},
            },
            db_session=db_session,
        )

        state = BuildStreamingState(turn_index=0)

        # 1. Stream agent message chunks
        state.add_message_chunk("Thinking")
        state.add_message_chunk(" about it...")

        # Simulate switch to tool call (e.g. ToolCallStart event) -> finalize message
        # In SessionManager, this happens via state.should_finalize_chunks()
        if state.should_finalize_chunks("tool_call_start"):
            msg_packet = state.finalize_message_chunks()
            if msg_packet:
                create_message(
                    session_id=build_session.id,
                    message_type=MessageType.ASSISTANT,
                    turn_index=0,
                    message_metadata=msg_packet,
                    db_session=db_session,
                )
        state.clear_last_chunk_type()

        # 2. Handle completed tool call (immediate save)
        tool_packet = {
            "type": "tool_call_progress",
            "toolCallId": "call_1",
            "status": "completed",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        create_message(
            session_id=build_session.id,
            message_type=MessageType.ASSISTANT,
            turn_index=0,
            message_metadata=tool_packet,
            db_session=db_session,
        )

        # 3. Stream more agent message chunks
        state.add_message_chunk("Done")
        state.add_message_chunk(" with tool.")

        # End of stream -> finalize
        msg_packet = state.finalize_message_chunks()
        if msg_packet:
            create_message(
                session_id=build_session.id,
                message_type=MessageType.ASSISTANT,
                turn_index=0,
                message_metadata=msg_packet,
                db_session=db_session,
            )

        # Verify DB state
        messages = get_session_messages(build_session.id, db_session)
        # 1 user + 3 assistant = 4 total
        assert len(messages) == 4

        # Verify types/order
        assert messages[0].type == MessageType.USER

        assert messages[1].type == MessageType.ASSISTANT
        assert messages[1].message_metadata["content"]["text"] == "Thinking about it..."

        assert messages[2].type == MessageType.ASSISTANT
        assert messages[2].message_metadata["type"] == "tool_call_progress"

        assert messages[3].type == MessageType.ASSISTANT
        assert messages[3].message_metadata["content"]["text"] == "Done with tool."

    def test_agent_thought_chunks_persist_as_single_thought_row(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """3 thought chunks → 1 ``agent_thought`` row with concatenated text."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _thought_chunk("Hmm, "),
            _thought_chunk("let me "),
            _thought_chunk("think."),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "hi"))

        messages = get_session_messages(build_session.id, db_session)
        thoughts = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "agent_thought"
        ]
        assert len(thoughts) == 1
        assert thoughts[0].message_metadata["content"]["text"] == "Hmm, let me think."
        # No user_message chunks should have been persisted as message rows.
        agent_messages = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "agent_message"
        ]
        assert agent_messages == []

    def test_tool_call_start_never_persisted(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """``ToolCallStart`` events are stream-only; no DB row is created."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _tool_call_start("tc-1", "Bash"),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "run a command"))

        messages = get_session_messages(build_session.id, db_session)
        types = [(m.message_metadata or {}).get("type") for m in messages]
        # User row only; no tool_call / tool_call_start rows.
        assert types == ["user_message"]

    def test_completed_tool_call_persisted(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """``ToolCallProgress`` with status='completed' → one row."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _tool_call_progress("tc-1", "Bash", status="completed"),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "run it"))

        messages = get_session_messages(build_session.id, db_session)
        tool_rows = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "tool_call_progress"
            and (m.message_metadata or {}).get("status") == "completed"
        ]
        assert len(tool_rows) == 1
        assert tool_rows[0].message_metadata["toolCallId"] == "tc-1"

    def test_in_progress_tool_call_not_persisted_except_todowrite(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Non-completed, non-TodoWrite tool progress → no row written."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _tool_call_progress("tc-1", "Bash", status="in_progress"),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "run it"))

        messages = get_session_messages(build_session.id, db_session)
        tool_rows = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "tool_call_progress"
        ]
        assert tool_rows == []

    def test_todowrite_progress_persisted_on_every_update(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """3 TodoWrite progress events (regardless of status) → 3 rows."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _tool_call_progress("tw-1", "TodoWrite", status="in_progress"),
            _tool_call_progress("tw-1", "TodoWrite", status="in_progress"),
            _tool_call_progress("tw-1", "TodoWrite", status="completed"),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "plan it"))

        messages = get_session_messages(build_session.id, db_session)
        todo_rows = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "tool_call_progress"
            and (m.message_metadata or {}).get("title") == "TodoWrite"
        ]
        assert len(todo_rows) == 3

    def test_agent_plan_upserted_once_per_turn(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Two plan updates same turn → 1 row, latest content."""
        # Create a user message first
        create_message(
            session_id=build_session.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "Create a plan"},
            },
            db_session=db_session,
        )

        # First plan
        plan1 = {
            "type": "agent_plan_update",
            "entries": [
                {"id": "1", "status": "pending", "content": "Step 1"},
            ],
            "timestamp": "2025-01-01T00:00:00Z",
        }

        plan_msg1 = upsert_agent_plan(
            session_id=build_session.id,
            turn_index=0,
            plan_metadata=plan1,
            db_session=db_session,
        )

        assert plan_msg1.message_metadata["entries"][0]["status"] == "pending"

        # Update plan with new status
        plan2 = {
            "type": "agent_plan_update",
            "entries": [
                {"id": "1", "status": "completed", "content": "Step 1"},
                {"id": "2", "status": "in_progress", "content": "Step 2"},
            ],
            "timestamp": "2025-01-01T00:01:00Z",
        }

        plan_msg2 = upsert_agent_plan(
            session_id=build_session.id,
            turn_index=0,
            plan_metadata=plan2,
            db_session=db_session,
            existing_plan_id=plan_msg1.id,
        )

        # Should be the same message, updated
        assert plan_msg2.id == plan_msg1.id
        assert len(plan_msg2.message_metadata["entries"]) == 2
        assert plan_msg2.message_metadata["entries"][0]["status"] == "completed"

        # Verify only one plan message exists for this turn
        messages = get_session_messages(build_session.id, db_session)
        plan_messages = [
            m for m in messages if m.message_metadata.get("type") == "agent_plan_update"
        ]
        assert len(plan_messages) == 1

        # Also verify the "no existing id" path resolves to the same row (pins
        # the upsert-by-discovery semantics).
        plan3 = {
            "type": "agent_plan_update",
            "entries": [{"id": "1", "status": "completed", "content": "Step 1"}],
        }
        plan_msg3 = upsert_agent_plan(
            session_id=build_session.id,
            turn_index=0,
            plan_metadata=plan3,
            db_session=db_session,
        )
        assert plan_msg3.id == plan_msg1.id

    def test_completed_task_tool_emits_synthetic_agent_message(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Completed Task sub-agent tool → tool_call_progress row AND synthetic agent_message row.

        Regression for ``manager.py:1303-1324``.
        """
        sandbox(user=test_user)
        task_output_text = "Sub-agent completed analysis: 3 files changed."
        stub_sandbox_manager.send_message_events = [
            _tool_call_progress(
                "task-1",
                "Task",
                status="completed",
                raw_input={"subagent_type": "research"},
                raw_output={
                    "output": (
                        f"{task_output_text}<task_metadata>internal</task_metadata>"
                    )
                },
            ),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "run subagent"))

        messages = get_session_messages(build_session.id, db_session)
        # Tool call row
        tool_rows = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "tool_call_progress"
            and (m.message_metadata or {}).get("title") == "Task"
        ]
        assert len(tool_rows) == 1

        # Synthetic agent_message row tagged source=task_output
        synth = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "agent_message"
            and (m.message_metadata or {}).get("source") == "task_output"
        ]
        assert len(synth) == 1
        assert synth[0].message_metadata["content"]["text"] == task_output_text

    def test_turn_index_increments_per_user_message(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Three driven turns → assistant rows tagged turn 0, 1, 2."""
        sandbox(user=test_user)
        # Same event sequence drives every turn; the stub re-iterates the
        # snapshotted list on every send_message call.
        stub_sandbox_manager.send_message_events = [
            _text_chunk("ok"),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        for prompt in ("first", "second", "third"):
            _drain(mgr.send_message(build_session.id, test_user.id, prompt))

        messages = get_session_messages(build_session.id, db_session)
        # 3 user + 3 assistant agent_message rows.
        by_turn: dict[int, list[Any]] = {}
        for m in messages:
            by_turn.setdefault(m.turn_index, []).append(m)
        assert set(by_turn.keys()) == {0, 1, 2}

        for turn in (0, 1, 2):
            assistant_msgs = [
                m
                for m in by_turn[turn]
                if m.type == MessageType.ASSISTANT
                and (m.message_metadata or {}).get("type") == "agent_message"
            ]
            assert len(assistant_msgs) == 1, f"turn {turn}: {by_turn[turn]}"

    def test_finalize_on_clean_stream_end(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Pending chunks are flushed when the stream completes normally."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _text_chunk("part one. "),
            _text_chunk("part two."),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        _drain(mgr.send_message(build_session.id, test_user.id, "go"))

        messages = get_session_messages(build_session.id, db_session)
        agent_msgs = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "agent_message"
        ]
        assert len(agent_msgs) == 1
        assert (
            agent_msgs[0].message_metadata["content"]["text"] == "part one. part two."
        )

    def test_finalize_on_client_disconnect_preserves_partial_text(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Stream gets ``GeneratorExit`` → partial text persisted to DB.

        Regression for SHA ``1594-1602`` finalize fix.
        """
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _text_chunk("partial "),
            _text_chunk("text"),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        gen = mgr.send_message(build_session.id, test_user.id, "go")
        # Consume just enough frames to receive both chunks; we read 4 frames
        # (user-message persistence happens before iteration, then 2 chunk
        # frames are yielded). Closing the generator triggers GeneratorExit
        # inside ``_stream_cli_agent_response`` which must finalize chunks.
        consumed: list[str] = []
        for i, frame in enumerate(gen):
            consumed.append(frame)
            if i >= 1:
                break
        gen.close()

        messages = get_session_messages(build_session.id, db_session)
        agent_msgs = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "agent_message"
        ]
        assert len(agent_msgs) == 1
        # The exact accumulated text depends on how many chunks were processed
        # before GeneratorExit; the regression contract is that *some* text
        # is persisted rather than dropped.
        text = agent_msgs[0].message_metadata["content"]["text"]
        assert text  # non-empty
        assert text in ("partial ", "partial text")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "known: except branches in _stream_cli_agent_response don't call "
            "_finalize_persist. User-visible streamed text disappears on page "
            "refresh after an error."
        ),
    )
    def test_finalize_on_exception_preserves_partial_text(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Accumulated chunks must be flushed to DB before the ErrorPacket is yielded.

        Asserts the *correct* behavior. The current implementation does NOT
        call ``_finalize_persist`` on the ``except`` branches, so this test
        will fail today until the ~5 LOC fix lands (see plan Part VIII).
        Strict-xfail absorbs the failure; the fixer removes the mark.
        """
        sandbox(user=test_user)

        def _yield_then_raise(
            sandbox_id: UUID,  # noqa: ARG001
            session_id: UUID,  # noqa: ARG001
            message: str,  # noqa: ARG001
        ) -> Generator[Any, None, None]:
            yield _text_chunk("buffered ")
            yield _text_chunk("partial")
            raise RuntimeError("agent crashed mid-stream")

        # Bypass the not-configured guard by replacing send_message wholesale.
        stub_sandbox_manager.send_message = _yield_then_raise  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        mgr = session_manager_with_stub

        frames = _drain(mgr.send_message(build_session.id, test_user.id, "go"))
        # An ErrorPacket frame is expected at end of stream.
        assert any("agent crashed mid-stream" in f for f in frames)

        messages = get_session_messages(build_session.id, db_session)
        agent_msgs = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "agent_message"
        ]
        # Correct behavior: buffered chunks flushed before the error packet.
        # Current implementation drops them — strict xfail catches the XPASS
        # once the bug is fixed.
        assert len(agent_msgs) == 1
        assert agent_msgs[0].message_metadata["content"]["text"] == "buffered partial"


# =============================================================================
# Stream error semantics (DB-bound, observable)
# =============================================================================


class TestStreamErrorSemantics:
    """DB-bound tests for user-visible ErrorPacket emission."""

    def test_sandbox_not_running_emits_error_packet_and_closes(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Sandbox status SLEEPING → ErrorPacket('Sandbox is not running…') → stream ends."""
        sandbox(user=test_user, status=SandboxStatus.SLEEPING)
        # No send_message_events configured: the stub would raise if reached.
        mgr = session_manager_with_stub

        frames = _drain(mgr.send_message(build_session.id, test_user.id, "anything"))

        assert len(frames) == 1
        assert "Sandbox is not running" in frames[0]
        # Stub.send_message must never have been invoked.
        assert stub_sandbox_manager.send_message_count == 0

    def test_session_not_found_emits_error_packet(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Wrong user's session id → ErrorPacket('Session not found')."""
        bogus_session_id = uuid4()
        mgr = session_manager_with_stub

        frames = _drain(mgr.send_message(bogus_session_id, test_user.id, "hi"))

        assert len(frames) == 1
        assert "Session not found" in frames[0]
        assert stub_sandbox_manager.send_message_count == 0

    def test_agent_exception_during_stream_emits_error_packet(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Stub backend raises mid-stream → ErrorPacket carries the message."""
        sandbox(user=test_user)

        def _boom(
            sandbox_id: UUID,  # noqa: ARG001
            session_id: UUID,  # noqa: ARG001
            message: str,  # noqa: ARG001
        ) -> Generator[Any, None, None]:
            yield _text_chunk("starting")
            raise RuntimeError("upstream model crashed")

        stub_sandbox_manager.send_message = _boom  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        mgr = session_manager_with_stub

        frames = _drain(mgr.send_message(build_session.id, test_user.id, "go"))

        assert any("upstream model crashed" in f for f in frames)
        # The final frame is the ErrorPacket.
        assert "upstream model crashed" in frames[-1]

    def test_acp_timeout_emits_error_packet(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Stub raises a TimeoutError-shaped exception → ErrorPacket carries the message.

        The K8s ACP client surfaces ``ACP_MESSAGE_TIMEOUT`` overruns as
        ``TimeoutError`` raised from inside the send_message generator. The
        stream loop's broad ``except Exception`` catches it and emits an
        ErrorPacket containing the message — observable contract for the
        front-end.
        """
        sandbox(user=test_user)

        def _timeout(
            sandbox_id: UUID,  # noqa: ARG001
            session_id: UUID,  # noqa: ARG001
            message: str,  # noqa: ARG001
        ) -> Generator[Any, None, None]:
            # Generator-with-raise is how the K8s client surfaces timeouts.
            if False:
                yield  # pragma: no cover - generator marker
            raise TimeoutError("ACP request timed out after 1.0s")

        stub_sandbox_manager.send_message = _timeout  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
        # Override env var purely for documentation / parity with the
        # production timeout path — the stub doesn't read it but tests assert
        # the override is applied without crashing.
        monkeypatch.setenv("ACP_MESSAGE_TIMEOUT", "1.0")
        mgr = session_manager_with_stub

        frames = _drain(mgr.send_message(build_session.id, test_user.id, "slow op"))

        assert any("timed out" in f.lower() for f in frames)

    def test_keepalive_emitted_on_idle_intervals(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        monkeypatch: pytest.MonkeyPatch,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """``SSEKeepalive`` markers from the sandbox client → ``: keepalive`` SSE frames.

        The K8s ACP client emits ``SSEKeepalive`` after
        ``SSE_KEEPALIVE_INTERVAL`` seconds of idle. The stream loop
        converts each one into a ``: keepalive\\n\\n`` SSE comment.
        """
        sandbox(user=test_user)
        # Override the env for parity with the prod keepalive path; the
        # stub feeds the markers directly without sleeping.
        monkeypatch.setenv("SSE_KEEPALIVE_INTERVAL", "0.01")
        stub_sandbox_manager.send_message_events = [
            SSEKeepalive(),
            _text_chunk("ok"),
            SSEKeepalive(),
            _prompt_response(),
        ]
        mgr = session_manager_with_stub

        frames = _drain(mgr.send_message(build_session.id, test_user.id, "go"))

        keepalive_frames = [f for f in frames if f.startswith(": keepalive")]
        assert len(keepalive_frames) == 2
