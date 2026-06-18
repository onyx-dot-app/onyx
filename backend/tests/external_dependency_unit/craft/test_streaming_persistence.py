"""Streaming persistence tests (ext-dep).

These cover what ``persist_sandbox_event`` actually writes to the DB
(assistant/thought rows, tool-call gating, plan upsert, turn indexing, finalize
semantics). Tests drive the same shared helpers used by the background
interactive-turn runner against Postgres with a stubbed ``SandboxManager``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import upsert_agent_plan
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.event_schema import ToolCallStart
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.streaming import BuildStreamingState
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


def _drive_persisted_turn(
    *,
    db_session: Session,
    mgr: SessionManager,
    build_session: BuildSession,
    user: User,
    content: str,
) -> None:
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    assert sandbox is not None

    turn_index = (
        db_session.query(BuildMessage)
        .filter(
            BuildMessage.session_id == build_session.id,
            BuildMessage.type == MessageType.USER,
        )
        .count()
    )
    create_message(
        session_id=build_session.id,
        message_type=MessageType.USER,
        turn_index=turn_index,
        message_metadata={
            "type": "user_message",
            "content": {"type": "text", "text": content},
        },
        db_session=db_session,
    )

    state = BuildStreamingState(turn_index=turn_index)
    try:
        for sandbox_event in mgr.yield_sandbox_events(
            sandbox.id,
            build_session.id,
            content,
            should_interrupt=lambda: False,
        ):
            if isinstance(sandbox_event, SSEKeepalive):
                continue
            mgr.persist_sandbox_event(build_session.id, state, sandbox_event)
    finally:
        mgr.finalize_persist(build_session.id, state)
    db_session.commit()


# =============================================================================
# Streaming persistence (DB-bound)
# =============================================================================


class TestStreamingPersistence:
    """DB-bound tests for `_persist_sandbox_event` behavior."""

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

    def test_agent_thought_chunks_persist_as_single_collapsed_row(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """3 thought chunks stream live, then persist as one ``agent_thought`` row."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _thought_chunk("Hmm, "),
            _thought_chunk("let me "),
            _thought_chunk("think."),
            _prompt_response(),
        ]
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="hi",
        )

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

    def test_existing_session_event_subscription_streams_without_persisting(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Live viewers receive ACP SSE without becoming a second DB writer."""
        sandbox_row = sandbox(user=test_user)
        build_session.opencode_session_id = "opencode-live-session"
        db_session.commit()

        stub_sandbox_manager.subscribe_to_opencode_session_events = [
            _text_chunk("live text"),
            SSEKeepalive(),
            _prompt_response(),
        ]

        frames = list(
            session_manager_with_stub.subscribe_to_existing_session_events(
                build_session.id,
                test_user.id,
                keepalive_seconds=0.5,
            )
        )

        assert stub_sandbox_manager.subscribe_to_opencode_session_count == 1
        assert stub_sandbox_manager.last_subscribe_to_opencode_session_payload == {
            "sandbox_id": sandbox_row.id,
            "opencode_session_id": "opencode-live-session",
            "directory": f"/workspace/sessions/{build_session.id}",
            "keepalive_seconds": 0.5,
        }
        assert ": keepalive\n\n" in frames

        data_frames = [frame for frame in frames if frame.startswith("event: message")]
        payloads = [
            json.loads(frame.split("data: ", maxsplit=1)[1]) for frame in data_frames
        ]
        assert [payload["type"] for payload in payloads] == [
            "agent_message_chunk",
            "prompt_response",
        ]
        assert get_session_messages(build_session.id, db_session) == []

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
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="run a command",
        )

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
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="run it",
        )

        messages = get_session_messages(build_session.id, db_session)
        tool_rows = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "tool_call_progress"
            and (m.message_metadata or {}).get("status") == "completed"
        ]
        assert len(tool_rows) == 1
        assert tool_rows[0].message_metadata["toolCallId"] == "tc-1"

    def test_failed_tool_call_persisted(
        self,
        db_session: Session,
        test_user: User,
        build_session: BuildSession,
        sandbox: Callable[..., Sandbox],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """``ToolCallProgress`` with status='failed' → one row, so failed
        tool calls survive session reload."""
        sandbox(user=test_user)
        stub_sandbox_manager.send_message_events = [
            _tool_call_progress(
                "tc-1",
                "Bash",
                status="failed",
                raw_output={"output": "ls: cannot access '/x': No such file"},
            ),
            _prompt_response(),
        ]
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="run it",
        )

        messages = get_session_messages(build_session.id, db_session)
        tool_rows = [
            m
            for m in messages
            if (m.message_metadata or {}).get("type") == "tool_call_progress"
            and (m.message_metadata or {}).get("status") == "failed"
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
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="run it",
        )

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
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="plan it",
        )

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
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="run subagent",
        )

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
        for prompt in ("first", "second", "third"):
            _drive_persisted_turn(
                db_session=db_session,
                mgr=session_manager_with_stub,
                build_session=build_session,
                user=test_user,
                content=prompt,
            )

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
        _drive_persisted_turn(
            db_session=db_session,
            mgr=session_manager_with_stub,
            build_session=build_session,
            user=test_user,
            content="go",
        )

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
