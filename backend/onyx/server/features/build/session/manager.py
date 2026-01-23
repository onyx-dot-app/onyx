"""Public interface for session operations.

SessionManager is the main entry point for build session lifecycle management.
It orchestrates session CRUD, message handling, artifact management, and file system access.
"""

import io
import json
import mimetypes
import os
import zipfile
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from acp.schema import AgentMessageChunk
from acp.schema import AgentPlanUpdate
from acp.schema import AgentThoughtChunk
from acp.schema import CurrentModeUpdate
from acp.schema import Error as ACPError
from acp.schema import PromptResponse
from acp.schema import ToolCallProgress
from acp.schema import ToolCallStart
from sqlalchemy.orm import Session as DBSession

from onyx.configs.constants import MessageType
from onyx.db.enums import SandboxStatus
from onyx.db.llm import fetch_default_provider
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import User
from onyx.llm.factory import get_default_llm
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import FileSystemEntry
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.api.packets import BuildPacket
from onyx.server.features.build.api.packets import ErrorPacket
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.configs import PERSISTENT_DOCUMENT_STORAGE_PATH
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.configs import USER_UPLOADS_DIRECTORY
from onyx.server.features.build.db.build_session import create_build_session__no_commit
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import delete_build_session__no_commit
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import get_empty_session_for_user
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import get_user_build_sessions
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.build_session import upsert_agent_plan
from onyx.server.features.build.db.sandbox import allocate_nextjs_port
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import get_running_sandbox_count_by_tenant
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox import get_sandbox_manager
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class BuildStreamingState:
    """Container for accumulating state during ACP streaming.

    Similar to ChatStateContainer but adapted for ACP packet types.
    Accumulates chunks and tracks pending tool calls until completion.

    Usage:
        state = BuildStreamingState(turn_index=0)

        # During streaming:
        for packet in stream:
            if packet.type == "agent_message_chunk":
                state.add_message_chunk(packet.content.text)
            elif packet.type == "tool_call_progress" and packet.status == "completed":
                state.add_completed_tool_call(packet_data)
            # etc.

        # At end of streaming, call finalize methods and save
    """

    def __init__(self, turn_index: int) -> None:
        """Initialize streaming state for a turn.

        Args:
            turn_index: The 0-indexed user message number this turn belongs to
        """
        self.turn_index = turn_index

        # Accumulated text chunks (similar to answer_tokens in ChatStateContainer)
        self.message_chunks: list[str] = []
        self.thought_chunks: list[str] = []

        # For upserting agent_plan_update - track ID so we can update in place
        self.plan_message_id: UUID | None = None

        # Track what type of chunk we were last receiving
        self._last_chunk_type: str | None = None

    def add_message_chunk(self, text: str) -> None:
        """Accumulate message text."""
        self.message_chunks.append(text)
        self._last_chunk_type = "message"

    def add_thought_chunk(self, text: str) -> None:
        """Accumulate thought text."""
        self.thought_chunks.append(text)
        self._last_chunk_type = "thought"

    def finalize_message_chunks(self) -> dict[str, Any] | None:
        """Build a synthetic packet with accumulated message text.

        Returns:
            A synthetic agent_message packet or None if no chunks accumulated
        """
        if not self.message_chunks:
            return None

        full_text = "".join(self.message_chunks)
        result = {
            "type": "agent_message",
            "content": {"type": "text", "text": full_text},
            "sessionUpdate": "agent_message",
        }
        self.message_chunks.clear()
        return result

    def finalize_thought_chunks(self) -> dict[str, Any] | None:
        """Build a synthetic packet with accumulated thought text.

        Returns:
            A synthetic agent_thought packet or None if no chunks accumulated
        """
        if not self.thought_chunks:
            return None

        full_text = "".join(self.thought_chunks)
        result = {
            "type": "agent_thought",
            "content": {"type": "text", "text": full_text},
            "sessionUpdate": "agent_thought",
        }
        self.thought_chunks.clear()
        return result

    def should_finalize_chunks(self, new_packet_type: str) -> bool:
        """Check if we should finalize pending chunks before processing new packet.

        We finalize when the packet type changes from message/thought chunks
        to something else (or to a different chunk type).
        """
        if self._last_chunk_type is None:
            return False

        # If we were receiving message chunks and now get something else
        if (
            self._last_chunk_type == "message"
            and new_packet_type != "agent_message_chunk"
        ):
            return True

        # If we were receiving thought chunks and now get something else
        if (
            self._last_chunk_type == "thought"
            and new_packet_type != "agent_thought_chunk"
        ):
            return True

        return False

    def clear_last_chunk_type(self) -> None:
        """Clear the last chunk type tracking after finalization."""
        self._last_chunk_type = None


# Build session naming prompts (similar to chat naming)
BUILD_NAMING_SYSTEM_PROMPT = """
Given the user's build request, provide a SHORT name for the build session. \
Focus on the main task or goal the user wants to accomplish.

IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS CONCISE AS POSSIBLE. \
NEVER USE MORE THAN 5 WORDS, LESS IS FINE.
""".strip()

BUILD_NAMING_USER_PROMPT = """
User's request: {user_message}

Provide a short name for this build session.
""".strip()


# Hidden directories/files to filter from listings
HIDDEN_PATTERNS = {
    ".venv",
    ".git",
    ".next",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    ".env",
    ".gitignore",
}


class RateLimitError(Exception):
    """Exception raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        messages_used: int,
        limit: int,
        reset_timestamp: str | None = None,
    ):
        super().__init__(message)
        self.messages_used = messages_used
        self.limit = limit
        self.reset_timestamp = reset_timestamp


class SessionManager:
    """Public interface for session operations.

    Orchestrates session lifecycle, messaging, artifacts, and file access.
    Uses SandboxManager internally for sandbox-related operations.

    Unlike SandboxManager, this is NOT a singleton - each instance is bound
    to a specific database session for the duration of a request.

    Usage:
        session_manager = SessionManager(db_session)
        sessions = session_manager.list_sessions(user_id)
    """

    def __init__(self, db_session: DBSession) -> None:
        """Initialize the SessionManager with a database session.

        Args:
            db_session: The SQLAlchemy database session to use for all operations
        """
        self._db_session = db_session
        self._sandbox_manager = get_sandbox_manager()

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def check_rate_limit(self, user: User) -> None:
        """
        Check build mode rate limits for a user.

        Args:
            user: The user to check rate limits for

        Raises:
            RateLimitError: If rate limit is exceeded
        """
        # Skip rate limiting for self-hosted deployments
        if not MULTI_TENANT:
            return

        rate_limit_status = get_user_rate_limit_status(user, self._db_session)
        if rate_limit_status.is_limited:
            raise RateLimitError(
                message=(
                    f"Rate limit exceeded. You have used "
                    f"{rate_limit_status.messages_used}/{rate_limit_status.limit} messages. "
                    f"Limit resets at {rate_limit_status.reset_timestamp}."
                    if rate_limit_status.reset_timestamp
                    else "This is a lifetime limit."
                ),
                messages_used=rate_limit_status.messages_used,
                limit=rate_limit_status.limit,
                reset_timestamp=rate_limit_status.reset_timestamp,
            )

    # =========================================================================
    # Session CRUD Operations
    # =========================================================================

    def list_sessions(
        self,
        user_id: UUID,
    ) -> list[BuildSession]:
        """Get all build sessions for a user.

        Args:
            user_id: The user ID

        Returns:
            List of BuildSession models ordered by most recent first
        """
        return get_user_build_sessions(user_id, self._db_session)

    def create_session__no_commit(
        self,
        user_id: UUID,
        name: str | None = None,
    ) -> BuildSession:
        """
        Create a new build session with a sandbox.

        NOTE: This method does NOT commit the transaction. The caller is
        responsible for committing after this method returns successfully.
        This allows the entire operation to be atomic at the endpoint level.

        Args:
            user_id: The user ID
            name: Optional session name

        Returns:
            The created BuildSession model

        Raises:
            ValueError: If max concurrent sandboxes reached or no LLM provider
            RuntimeError: If sandbox provisioning fails
        """
        tenant_id = get_current_tenant_id()

        # Check sandbox limits for multi-tenant deployments
        if MULTI_TENANT:
            from onyx.server.features.build.configs import (
                SANDBOX_MAX_CONCURRENT_PER_ORG,
            )

            running_count = get_running_sandbox_count_by_tenant(
                self._db_session, tenant_id
            )
            if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
                raise ValueError(
                    f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) reached"
                )

        # Fetch LLM provider configuration
        llm_provider = fetch_default_provider(self._db_session)
        if not llm_provider:
            raise ValueError("No default LLM provider configured")

        llm_config = LLMProviderConfig(
            provider=llm_provider.provider,
            model_name=llm_provider.default_model_name,
            api_key=llm_provider.api_key,
            api_base=llm_provider.api_base,
        )

        # Allocate port for local backend
        nextjs_port: int | None = None
        if SANDBOX_BACKEND == SandboxBackend.LOCAL:
            nextjs_port = allocate_nextjs_port(self._db_session)

        # Build user-specific path for FILE_SYSTEM documents (sandbox isolation)
        # Each user's sandbox can only access documents they created
        if PERSISTENT_DOCUMENT_STORAGE_PATH:
            user_file_system_path = str(
                Path(PERSISTENT_DOCUMENT_STORAGE_PATH) / str(user_id)
            )
            # Ensure the user's document directory exists
            Path(user_file_system_path).mkdir(parents=True, exist_ok=True)
        else:
            user_file_system_path = "/tmp/onyx-files"

        # Create BuildSession record (uses flush, caller commits)
        build_session = create_build_session__no_commit(
            user_id, self._db_session, name=name
        )
        session_id = str(build_session.id)
        logger.info(f"Created build session {session_id} for user {user_id}")

        # Create Sandbox record (uses flush, caller commits)
        sandbox = create_sandbox__no_commit(
            db_session=self._db_session,
            session_id=build_session.id,
            nextjs_port=nextjs_port,
        )
        sandbox_id = sandbox.id
        logger.info(f"Created sandbox record {sandbox_id} for session {session_id}")

        # Provision sandbox (no DB operations inside)
        sandbox_info = self._sandbox_manager.provision(
            sandbox_id=sandbox_id,
            user_id=user_id,
            tenant_id=tenant_id,
            file_system_path=user_file_system_path,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
        )

        # Update sandbox record with status from provisioning
        sandbox.nextjs_port = sandbox_info.nextjs_port
        sandbox.status = sandbox_info.status
        self._db_session.flush()

        logger.info(
            f"Successfully created session {session_id} with sandbox for user {user_id}"
        )

        return build_session

    def get_or_create_empty_session(self, user_id: UUID) -> BuildSession:
        """Get existing empty session or create a new one with provisioned sandbox.

        Used for pre-provisioning sandboxes when user lands on /build/v1.
        Returns existing recent empty session if one exists, otherwise creates new.

        Args:
            user_id: The user ID

        Returns:
            BuildSession (existing empty or newly created)

        Raises:
            ValueError: If max concurrent sandboxes reached
            RuntimeError: If sandbox provisioning fails
        """
        existing = get_empty_session_for_user(user_id, self._db_session)
        if existing:
            logger.info(
                f"Returning existing empty session {existing.id} for user {user_id}"
            )
            return existing
        return self.create_session__no_commit(user_id=user_id)

    def get_session(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> BuildSession | None:
        """
        Get a specific build session.

        Also updates the last activity timestamp.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            BuildSession model or None if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session:
            update_session_activity(session_id, self._db_session)
            self._db_session.refresh(session)
        return session

    def generate_session_name(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> str | None:
        """
        Generate a session name using LLM based on the first user message.

        Args:
            session_id: The session UUID
            user_id: The user ID (for ownership verification)

        Returns:
            Generated session name or None if session not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        return self._generate_session_name(session_id)

    def update_session_name(
        self,
        session_id: UUID,
        user_id: UUID,
        name: str | None = None,
    ) -> BuildSession | None:
        """
        Update the name of a build session.

        If name is None, auto-generates a name using LLM based on the first
        user message in the session.

        Args:
            session_id: The session UUID
            user_id: The user ID
            name: The new session name (if None, auto-generates using LLM)

        Returns:
            Updated BuildSession model or None if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        if name is not None:
            # Manual rename
            session.name = name
        else:
            # Auto-generate name from first user message using LLM
            session.name = self._generate_session_name(session_id)

        update_session_activity(session_id, self._db_session)
        self._db_session.commit()
        self._db_session.refresh(session)
        return session

    def _generate_session_name(self, session_id: UUID) -> str:
        """
        Generate a session name using LLM based on the first user message.

        Args:
            session_id: The session UUID

        Returns:
            Generated session name or fallback name
        """
        # Get messages to find first user message
        messages = get_session_messages(session_id, self._db_session)
        first_user_msg = next((m for m in messages if m.type == MessageType.USER), None)

        if not first_user_msg:
            return f"Build Session {str(session_id)[:8]}"

        # Extract text from message_metadata
        metadata = first_user_msg.message_metadata
        if not metadata:
            return f"Build Session {str(session_id)[:8]}"

        # Handle user_message packet structure: {type: "user_message", content: {type: "text", text: "..."}}
        content = metadata.get("content", {})
        if isinstance(content, dict):
            user_message = content.get("text", "")
        else:
            user_message = str(content) if content else ""

        if not user_message:
            return f"Build Session {str(session_id)[:8]}"

        # Use LLM to generate a concise session name
        try:
            llm = get_default_llm()
            prompt_messages: LanguageModelInput = [
                SystemMessage(content=BUILD_NAMING_SYSTEM_PROMPT),
                UserMessage(
                    content=BUILD_NAMING_USER_PROMPT.format(
                        user_message=user_message[:500]  # Limit input size
                    )
                ),
            ]
            response = llm.invoke(prompt_messages, reasoning_effort=ReasoningEffort.OFF)
            generated_name = llm_response_to_string(response).strip().strip('"')

            # Ensure the name isn't too long (max 50 chars)
            if len(generated_name) > 50:
                generated_name = generated_name[:47] + "..."

            return (
                generated_name
                if generated_name
                else f"Build Session {str(session_id)[:8]}"
            )
        except Exception as e:
            logger.warning(f"Failed to generate session name with LLM: {e}")
            # Fallback to simple truncation
            return user_message[:40].strip() + ("..." if len(user_message) > 40 else "")

    def delete_session(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Delete a build session and all associated data.

        Terminates any running sandbox before deletion. This operation is atomic -
        if sandbox termination fails, the session is NOT deleted.

        NOTE: This method does NOT commit the transaction. The caller is
        responsible for committing after this method returns successfully.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            True if deleted, False if not found

        Raises:
            RuntimeError: If sandbox termination fails
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return False

        # Terminate sandbox if running - raises on failure
        if session.sandbox and session.sandbox.status in [
            SandboxStatus.RUNNING,
            SandboxStatus.PROVISIONING,
        ]:
            logger.info(f"Terminating sandbox before deleting session {session_id}")
            sandbox_id = session.sandbox.id
            self._sandbox_manager.terminate(sandbox_id)
            # Update status after termination (sandbox manager no longer does this)
            update_sandbox_status__no_commit(
                self._db_session, sandbox_id, SandboxStatus.TERMINATED
            )

        # Delete session (uses flush, caller commits)
        return delete_build_session__no_commit(session_id, user_id, self._db_session)

    # =========================================================================
    # Message Operations
    # =========================================================================

    def list_messages(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> list[BuildMessage] | None:
        """
        Get all messages for a session.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            List of BuildMessage models or None if session not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None
        return get_session_messages(session_id, self._db_session)

    def send_message(
        self,
        session_id: UUID,
        user_id: UUID,
        content: str,
    ) -> Generator[str, None, None]:
        """
        Send a message to the CLI agent and stream the response as SSE events.

        Validates session, saves user message, streams agent response,
        and saves assistant response to database.

        Args:
            session_id: The session UUID
            user_id: The user ID
            content: The message content

        Yields:
            SSE formatted event strings
        """
        yield from self._stream_cli_agent_response(session_id, content, user_id)

    def _stream_cli_agent_response(
        self,
        session_id: UUID,
        user_message_content: str,
        user_id: UUID,
    ) -> Generator[str, None, None]:
        """
        Stream the CLI agent's response using SSE format.

        Executes the agent via SandboxManager and streams events back to the client.
        Uses BuildStreamingState to accumulate chunks and track tool calls.
        At the end of streaming, saves accumulated state to the database.

        Storage behavior:
        - User message: Saved immediately at start
        - agent_message_chunk: Accumulated, saved as one synthetic packet at end/type change
        - agent_thought_chunk: Accumulated, saved as one synthetic packet at end/type change
        - tool_call_start: Streamed to frontend only, not saved
        - tool_call_progress: Only saved when status="completed"
        - agent_plan_update: Upserted (only latest plan kept per turn)
        """

        def _serialize_acp_event(event: Any, event_type: str) -> str:
            """Serialize an ACP event to SSE format, preserving ALL ACP data."""
            if hasattr(event, "model_dump"):
                data = event.model_dump(mode="json", by_alias=True, exclude_none=False)
            else:
                data = {"raw": str(event)}

            data["type"] = event_type
            data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

            return f"event: message\ndata: {json.dumps(data)}\n\n"

        def _format_packet_event(packet: BuildPacket) -> str:
            """Format a BuildPacket as SSE."""
            return f"event: message\ndata: {packet.model_dump_json(by_alias=True)}\n\n"

        def _extract_text_from_content(content: Any) -> str:
            """Extract text from ACP content structure."""
            if content is None:
                return ""
            if hasattr(content, "type") and content.type == "text":
                return getattr(content, "text", "") or ""
            if isinstance(content, list):
                texts = []
                for block in content:
                    if hasattr(block, "type") and block.type == "text":
                        texts.append(getattr(block, "text", "") or "")
                return "".join(texts)
            return ""

        def _save_pending_chunks(state: BuildStreamingState) -> None:
            """Save any pending accumulated chunks to the database."""
            # Finalize message chunks
            message_packet = state.finalize_message_chunks()
            if message_packet:
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    turn_index=state.turn_index,
                    message_metadata=message_packet,
                    db_session=self._db_session,
                )

            # Finalize thought chunks
            thought_packet = state.finalize_thought_chunks()
            if thought_packet:
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    turn_index=state.turn_index,
                    message_metadata=thought_packet,
                    db_session=self._db_session,
                )

            state.clear_last_chunk_type()

        def _save_build_turn(state: BuildStreamingState) -> None:
            """Save all accumulated state at the end of streaming.

            Similar to save_chat_turn() in the main chat flow.
            """
            # 1. Save any remaining accumulated chunks
            _save_pending_chunks(state)

        # Initialize packet logging
        packet_logger = get_packet_logger()

        try:
            # Verify session exists and belongs to user
            session = get_build_session(session_id, user_id, self._db_session)
            if session is None:
                error_packet = ErrorPacket(message="Session not found")
                packet_logger.log("error", error_packet.model_dump())
                yield _format_packet_event(error_packet)
                return

            # Check if sandbox is running
            if not session.sandbox or session.sandbox.status != SandboxStatus.RUNNING:
                error_packet = ErrorPacket(
                    message="Sandbox is not running. Please wait for it to start."
                )
                packet_logger.log("error", error_packet.model_dump())
                yield _format_packet_event(error_packet)
                return

            # Update last activity timestamp
            update_session_activity(session_id, self._db_session)

            # Calculate turn_index BEFORE saving user message
            # turn_index = count of existing USER messages (this will be the Nth user message)

            # Get count of user messages to determine turn index
            existing_user_count = (
                self._db_session.query(BuildMessage)
                .filter(
                    BuildMessage.session_id == session_id,
                    BuildMessage.type == MessageType.USER,
                )
                .count()
            )
            turn_index = existing_user_count  # This user message is the Nth (0-indexed)

            # Save user message to database
            user_message_metadata = {
                "type": "user_message",
                "content": {"type": "text", "text": user_message_content},
            }
            create_message(
                session_id=session_id,
                message_type=MessageType.USER,
                turn_index=turn_index,
                message_metadata=user_message_metadata,
                db_session=self._db_session,
            )

            # Initialize streaming state for this turn
            state = BuildStreamingState(turn_index=turn_index)

            # Get sandbox
            sandbox = get_sandbox_by_session_id(self._db_session, session_id)
            if sandbox is None:
                error_packet = ErrorPacket(message="Sandbox not found")
                packet_logger.log("error", error_packet.model_dump())
                yield _format_packet_event(error_packet)
                return

            sandbox_id = sandbox.id

            # Stream ACP events directly to frontend
            for acp_event in self._sandbox_manager.send_message(
                sandbox_id, user_message_content
            ):
                # Check if we need to finalize pending chunks before processing
                event_type = self._get_event_type(acp_event)
                if state.should_finalize_chunks(event_type):
                    _save_pending_chunks(state)

                # Pass through ACP events with snake_case type names
                if isinstance(acp_event, AgentMessageChunk):
                    text = _extract_text_from_content(acp_event.content)
                    if text:
                        state.add_message_chunk(text)
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "agent_message_chunk"
                    packet_logger.log("agent_message_chunk", event_data)
                    yield _serialize_acp_event(acp_event, "agent_message_chunk")

                elif isinstance(acp_event, AgentThoughtChunk):
                    text = _extract_text_from_content(acp_event.content)
                    if text:
                        state.add_thought_chunk(text)
                    packet_logger.log(
                        "agent_thought_chunk",
                        acp_event.model_dump(mode="json", by_alias=True),
                    )
                    yield _serialize_acp_event(acp_event, "agent_thought_chunk")

                elif isinstance(acp_event, ToolCallStart):
                    # Stream to frontend but don't save - wait for completion
                    packet_logger.log(
                        "tool_call_start",
                        acp_event.model_dump(mode="json", by_alias=True),
                    )
                    yield _serialize_acp_event(acp_event, "tool_call_start")

                elif isinstance(acp_event, ToolCallProgress):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "tool_call_progress"
                    event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

                    # Check if this is a TodoWrite tool call
                    tool_name = (event_data.get("title") or "").lower()
                    is_todo_write = tool_name in ("todowrite", "todo_write")

                    # Check if this is a Task (subagent) tool call
                    raw_input = event_data.get("rawInput") or {}
                    is_task_tool = (
                        tool_name == "task"
                        or raw_input.get("subagent_type") is not None
                        or raw_input.get("subagentType") is not None
                    )

                    # Save to DB:
                    # - For TodoWrite: Save every progress update (todos change frequently)
                    # - For other tools: Only save when status="completed"
                    if is_todo_write or acp_event.status == "completed":
                        create_message(
                            session_id=session_id,
                            message_type=MessageType.ASSISTANT,
                            turn_index=state.turn_index,
                            message_metadata=event_data,
                            db_session=self._db_session,
                        )

                    # For completed Task tools, also save the output as an agent_message
                    # This allows the task output to be rendered as assistant text on reload
                    if is_task_tool and acp_event.status == "completed":
                        raw_output = event_data.get("rawOutput") or {}
                        task_output = raw_output.get("output")
                        if task_output and isinstance(task_output, str):
                            # Strip task_metadata from the output
                            metadata_idx = task_output.find("<task_metadata>")
                            if metadata_idx >= 0:
                                task_output = task_output[:metadata_idx].strip()

                            if task_output:
                                # Create agent_message packet for the task output
                                task_output_packet = {
                                    "type": "agent_message",
                                    "content": {"type": "text", "text": task_output},
                                    "source": "task_output",
                                    "timestamp": datetime.now(
                                        tz=timezone.utc
                                    ).isoformat(),
                                }
                                create_message(
                                    session_id=session_id,
                                    message_type=MessageType.ASSISTANT,
                                    turn_index=state.turn_index,
                                    message_metadata=task_output_packet,
                                    db_session=self._db_session,
                                )

                    packet_logger.log("tool_call_progress", event_data)
                    yield _serialize_acp_event(acp_event, "tool_call_progress")

                elif isinstance(acp_event, AgentPlanUpdate):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "agent_plan_update"
                    event_data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

                    # Upsert plan immediately
                    plan_msg = upsert_agent_plan(
                        session_id=session_id,
                        turn_index=state.turn_index,
                        plan_metadata=event_data,
                        db_session=self._db_session,
                        existing_plan_id=state.plan_message_id,
                    )
                    state.plan_message_id = plan_msg.id

                    packet_logger.log("agent_plan_update", event_data)
                    yield _serialize_acp_event(acp_event, "agent_plan_update")

                elif isinstance(acp_event, CurrentModeUpdate):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "current_mode_update"
                    packet_logger.log("current_mode_update", event_data)
                    yield _serialize_acp_event(acp_event, "current_mode_update")

                elif isinstance(acp_event, PromptResponse):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "prompt_response"
                    packet_logger.log("prompt_response", event_data)
                    yield _serialize_acp_event(acp_event, "prompt_response")

                elif isinstance(acp_event, ACPError):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "error"
                    packet_logger.log("error", event_data)
                    yield _serialize_acp_event(acp_event, "error")

                else:
                    # Unrecognized packet type - log it but don't stream to frontend
                    event_type_name = type(acp_event).__name__
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = f"unrecognized_{event_type_name.lower()}"
                    packet_logger.log(
                        f"unrecognized_{event_type_name.lower()}", event_data
                    )

            # Save all accumulated state at end of streaming
            _save_build_turn(state)

            # Update heartbeat after successful message exchange
            update_sandbox_heartbeat(self._db_session, sandbox_id)

        except ValueError as e:
            error_packet = ErrorPacket(message=str(e))
            packet_logger.log("error", error_packet.model_dump())
            logger.exception("ValueError in build message streaming")
            yield _format_packet_event(error_packet)
        except RuntimeError as e:
            error_packet = ErrorPacket(message=str(e))
            packet_logger.log("error", error_packet.model_dump())
            logger.exception(f"RuntimeError in build message streaming: {e}")
            yield _format_packet_event(error_packet)
        except Exception as e:
            error_packet = ErrorPacket(message=str(e))
            packet_logger.log("error", error_packet.model_dump())
            logger.exception("Unexpected error in build message streaming")
            yield _format_packet_event(error_packet)

    def _get_event_type(self, acp_event: Any) -> str:
        """Get the event type string for an ACP event."""
        if isinstance(acp_event, AgentMessageChunk):
            return "agent_message_chunk"
        elif isinstance(acp_event, AgentThoughtChunk):
            return "agent_thought_chunk"
        elif isinstance(acp_event, ToolCallStart):
            return "tool_call_start"
        elif isinstance(acp_event, ToolCallProgress):
            return "tool_call_progress"
        elif isinstance(acp_event, AgentPlanUpdate):
            return "agent_plan_update"
        elif isinstance(acp_event, CurrentModeUpdate):
            return "current_mode_update"
        elif isinstance(acp_event, PromptResponse):
            return "prompt_response"
        elif isinstance(acp_event, ACPError):
            return "error"
        return "unknown"

    # =========================================================================
    # Artifact Operations
    # =========================================================================

    def list_artifacts(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> list[dict[str, Any]] | None:
        """
        List artifacts generated in a session.

        Returns artifacts in the format expected by the frontend (matching ArtifactResponse).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            List of artifact dicts or None if session not found or user doesn't own session
        """
        import uuid

        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        artifacts: list[dict[str, Any]] = []
        output_dir = sandbox_path / "outputs"

        if not output_dir.exists():
            return artifacts

        now = datetime.now(timezone.utc)

        # Check for webapp
        web_dir = output_dir / "web"
        if web_dir.exists():
            artifacts.append(
                {
                    "id": str(uuid.uuid4()),
                    "session_id": str(session_id),
                    "type": "web_app",  # Use web_app to match streaming packet type
                    "name": "Web Application",
                    "path": "outputs/web",
                    "preview_url": None,  # Preview is via webapp URL, not artifact preview
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            )

        return artifacts

    def download_artifact(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> tuple[bytes, str, str] | None:
        """
        Download a specific artifact file.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the artifact

        Returns:
            Tuple of (content, mime_type, filename) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is a directory
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        file_path = sandbox_path / path

        if not file_path.exists():
            return None

        if file_path.is_dir():
            raise ValueError("Cannot download directory")

        content = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(file_path))

        return (content, mime_type or "application/octet-stream", file_path.name)

    def get_webapp_info(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any] | None:
        """
        Get webapp information for a session.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            Dict with has_webapp, webapp_url, and status, or None if session not found
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return {"has_webapp": False, "webapp_url": None, "status": "no_sandbox"}

        # Check if web directory exists
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        web_dir = sandbox_path / "outputs" / "web"
        has_webapp = web_dir.exists()

        # Build webapp URL if we have a port and webapp exists
        webapp_url = None
        if has_webapp and sandbox.nextjs_port:
            webapp_url = f"http://localhost:{sandbox.nextjs_port}"

        return {
            "has_webapp": has_webapp,
            "webapp_url": webapp_url,
            "status": sandbox.status.value,
        }

    def download_webapp_zip(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> tuple[bytes, str] | None:
        """
        Create a zip file of the webapp directory.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            Tuple of (zip_bytes, filename) or None if session/webapp not found
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        # Check if web directory exists
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        web_dir = sandbox_path / "outputs" / "web"

        if not web_dir.exists():
            return None

        # Create zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Walk through the web directory and add all files
            for root, _, files in os.walk(web_dir):
                for file in files:
                    file_path = Path(root) / file
                    # Create relative path for the zip archive
                    arcname = file_path.relative_to(web_dir)
                    zip_file.write(file_path, arcname)

        zip_buffer.seek(0)

        # Create filename with session name or ID
        session_name = session.name or f"session-{str(session_id)[:8]}"
        # Sanitize filename
        safe_name = "".join(
            c if c.isalnum() or c in ("-", "_") else "_" for c in session_name
        )
        filename = f"{safe_name}-webapp.zip"

        return zip_buffer.getvalue(), filename

    # =========================================================================
    # File System Operations
    # =========================================================================

    def list_directory(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> DirectoryListing | None:
        """
        List files and directories in the sandbox.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path from sandbox root (empty string for root)

        Returns:
            DirectoryListing with sorted entries (directories first) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        target_dir = sandbox_path / path if path else sandbox_path

        # Security check: ensure path doesn't escape sandbox via .. traversal
        try:
            normalized = os.path.normpath(str(target_dir))
            sandbox_normalized = os.path.normpath(str(sandbox_path))
            if not normalized.startswith(sandbox_normalized):
                raise ValueError("Access denied - path traversal")
        except ValueError:
            raise

        if not target_dir.exists():
            raise ValueError("Directory not found")

        if not target_dir.is_dir():
            raise ValueError("Path is not a directory")

        entries: list[FileSystemEntry] = []

        for item in target_dir.iterdir():
            # Filter hidden files and directories
            if item.name in HIDDEN_PATTERNS or item.name.startswith("."):
                continue

            rel_path = f"{path}/{item.name}" if path else item.name
            is_dir = item.is_dir()

            entry = FileSystemEntry(
                name=item.name,
                path=rel_path,
                is_directory=is_dir,
                size=item.stat().st_size if not is_dir else None,
                mime_type=mimetypes.guess_type(str(item))[0] if not is_dir else None,
            )
            entries.append(entry)

        # Sort: directories first, then files, both alphabetically
        entries.sort(key=lambda e: (not e.is_directory, e.name.lower()))

        return DirectoryListing(path=path, entries=entries)

    def upload_file(
        self,
        session_id: UUID,
        user_id: UUID,
        filename: str,
        content: bytes,
    ) -> tuple[str, int]:
        """Upload a file to the session's sandbox.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            filename: Sanitized filename (validation done at API layer)
            content: File content as bytes

        Returns:
            Tuple of (relative_path, size_bytes) where the file was saved

        Raises:
            ValueError: If session not found
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")

        # Filename is already sanitized by API layer
        safe_filename = filename

        # Get upload directory path
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        uploads_path = sandbox_path / USER_UPLOADS_DIRECTORY

        # Ensure uploads directory exists
        uploads_path.mkdir(parents=True, exist_ok=True)

        # Handle filename collisions by appending a number
        target_path = uploads_path / safe_filename
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            counter = 1
            while target_path.exists():
                target_path = uploads_path / f"{stem}_{counter}{suffix}"
                counter += 1
            safe_filename = target_path.name

        # Write file with read-only permissions (no execute)
        target_path.write_bytes(content)
        # Explicitly remove execute permissions: rw-r--r-- (644)
        target_path.chmod(0o644)

        # Return relative path from sandbox root
        relative_path = f"{USER_UPLOADS_DIRECTORY}/{safe_filename}"

        # Update heartbeat - file upload is user activity that keeps sandbox alive
        update_sandbox_heartbeat(self._db_session, sandbox.id)

        logger.info(
            f"Uploaded file to session {session_id}: {relative_path} "
            f"({len(content)} bytes)"
        )

        return relative_path, len(content)

    def delete_file(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> bool:
        """Delete a file from the session's sandbox.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the file (e.g., "user_uploaded_files/doc.pdf")

        Returns:
            True if file was deleted, False if not found

        Raises:
            ValueError: If session not found or path traversal attempted
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")

        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        file_path = sandbox_path / path

        # Security check: ensure path doesn't escape sandbox
        try:
            file_path = file_path.resolve()
            sandbox_path_resolved = sandbox_path.resolve()
            if not str(file_path).startswith(str(sandbox_path_resolved)):
                raise ValueError("Access denied - path traversal")
        except ValueError:
            raise

        if not file_path.exists():
            return False

        if file_path.is_dir():
            raise ValueError("Cannot delete directory")

        file_path.unlink()

        logger.info(f"Deleted file from session {session_id}: {path}")

        return True
