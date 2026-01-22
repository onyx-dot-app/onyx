"""
Test suite for build mode packet storage.

Tests the new packet storage behavior:
- All data stored in message_metadata as JSON (no content column)
- turn_index tracks which user message each assistant message belongs to
- Tool calls: Only save when status="completed"
- Message/thought chunks: Accumulated and saved as synthetic packets
- Agent plan updates: Upserted (only latest kept per turn)
"""

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import BuildSession
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import upsert_agent_plan
from onyx.server.features.build.session.manager import BuildStreamingState


class TestBuildMessageStorage:
    """Tests for build message storage in the database."""

    def test_create_message_with_metadata(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,
    ) -> None:
        """Test creating a message with JSON metadata and turn_index."""
        user_message_metadata = {
            "type": "user_message",
            "content": {"type": "text", "text": "Hello, world!"},
        }

        message = create_message(
            session_id=build_session.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata=user_message_metadata,
            db_session=db_session,
        )

        assert message.id is not None
        assert message.session_id == build_session.id
        assert message.type == MessageType.USER
        assert message.turn_index == 0
        assert message.message_metadata == user_message_metadata
        assert message.message_metadata["type"] == "user_message"
        assert message.message_metadata["content"]["text"] == "Hello, world!"

    def test_create_multiple_messages_with_turn_index(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,
    ) -> None:
        """Test creating multiple messages with correct turn_index values."""
        # First user message (turn 0)
        create_message(
            session_id=build_session.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "First question"},
            },
            db_session=db_session,
        )

        # Assistant response (turn 0)
        create_message(
            session_id=build_session.id,
            message_type=MessageType.ASSISTANT,
            turn_index=0,
            message_metadata={
                "type": "agent_message",
                "content": {"type": "text", "text": "First answer"},
            },
            db_session=db_session,
        )

        # Second user message (turn 1)
        create_message(
            session_id=build_session.id,
            message_type=MessageType.USER,
            turn_index=1,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "Second question"},
            },
            db_session=db_session,
        )

        # Assistant response (turn 1)
        create_message(
            session_id=build_session.id,
            message_type=MessageType.ASSISTANT,
            turn_index=1,
            message_metadata={
                "type": "agent_message",
                "content": {"type": "text", "text": "Second answer"},
            },
            db_session=db_session,
        )

        # Verify messages
        messages = get_session_messages(build_session.id, db_session)
        assert len(messages) == 4

        # Check turn indices
        turn_0_messages = [m for m in messages if m.turn_index == 0]
        turn_1_messages = [m for m in messages if m.turn_index == 1]

        assert len(turn_0_messages) == 2
        assert len(turn_1_messages) == 2

    def test_tool_call_completed_storage(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,
    ) -> None:
        """Test storing only completed tool calls."""
        # Create a user message first
        create_message(
            session_id=build_session.id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "Run a tool"},
            },
            db_session=db_session,
        )

        # Create a completed tool call
        tool_call_packet = {
            "type": "tool_call_progress",
            "toolCallId": "tool-123",
            "status": "completed",
            "kind": "bash",
            "title": "Running command",
            "rawOutput": "Command completed successfully",
            "timestamp": "2025-01-01T00:00:00Z",
        }

        message = create_message(
            session_id=build_session.id,
            message_type=MessageType.ASSISTANT,
            turn_index=0,
            message_metadata=tool_call_packet,
            db_session=db_session,
        )

        assert message.message_metadata["type"] == "tool_call_progress"
        assert message.message_metadata["status"] == "completed"
        assert message.message_metadata["toolCallId"] == "tool-123"

    def test_upsert_agent_plan(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,
    ) -> None:
        """Test upserting agent plan - only latest should be kept."""
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

    def test_upsert_agent_plan_without_existing_id(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,
    ) -> None:
        """Test upserting agent plan when we don't know the existing ID."""
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

        # First plan - no existing ID
        plan1 = {
            "type": "agent_plan_update",
            "entries": [{"id": "1", "status": "pending", "content": "Step 1"}],
        }

        plan_msg1 = upsert_agent_plan(
            session_id=build_session.id,
            turn_index=0,
            plan_metadata=plan1,
            db_session=db_session,
        )

        # Second plan - still no existing ID, should find and update
        plan2 = {
            "type": "agent_plan_update",
            "entries": [{"id": "1", "status": "completed", "content": "Step 1"}],
        }

        plan_msg2 = upsert_agent_plan(
            session_id=build_session.id,
            turn_index=0,
            plan_metadata=plan2,
            db_session=db_session,
        )

        # Should be the same message
        assert plan_msg2.id == plan_msg1.id

    def test_streaming_flow_db_calls(
        self,
        db_session: Session,
        build_session: BuildSession,
        tenant_context: None,
    ) -> None:
        """Test that streaming flow creates correct number of DB messages.

        Simulates:
        1. Agent message chunks -> 1 message
        2. Tool call -> 1 message
        3. Agent message chunks -> 1 message

        This verifies that we save parts of the turn as they finish, rather than
        buffering everything into one giant message or losing granularity.
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


class TestBuildStreamingState:
    """Tests for BuildStreamingState class."""

    def test_message_chunk_accumulation(self) -> None:
        """Test accumulating message chunks."""
        state = BuildStreamingState(turn_index=0)

        state.add_message_chunk("Hello, ")
        state.add_message_chunk("world!")

        packet = state.finalize_message_chunks()

        assert packet is not None
        assert packet["type"] == "agent_message"
        assert packet["content"]["text"] == "Hello, world!"

        # After finalize, chunks should be cleared
        assert len(state.message_chunks) == 0

    def test_thought_chunk_accumulation(self) -> None:
        """Test accumulating thought chunks."""
        state = BuildStreamingState(turn_index=0)

        state.add_thought_chunk("Thinking about ")
        state.add_thought_chunk("the problem...")

        packet = state.finalize_thought_chunks()

        assert packet is not None
        assert packet["type"] == "agent_thought"
        assert packet["content"]["text"] == "Thinking about the problem..."

    def test_should_finalize_chunks_on_type_change(self) -> None:
        """Test detection of when to finalize chunks."""
        state = BuildStreamingState(turn_index=0)

        # Add message chunk
        state.add_message_chunk("Hello")

        # Should finalize when receiving non-message packet
        assert state.should_finalize_chunks("tool_call_start") is True
        assert state.should_finalize_chunks("agent_plan_update") is True
        assert state.should_finalize_chunks("agent_thought_chunk") is True

        # Should NOT finalize for same type
        assert state.should_finalize_chunks("agent_message_chunk") is False

    def test_finalize_returns_none_when_empty(self) -> None:
        """Test that finalize returns None when no chunks accumulated."""
        state = BuildStreamingState(turn_index=0)

        assert state.finalize_message_chunks() is None
        assert state.finalize_thought_chunks() is None
