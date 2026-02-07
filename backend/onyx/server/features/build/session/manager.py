"""Public interface for session operations.

SessionManager is the main entry point for build session lifecycle management.
It orchestrates session CRUD, message handling, artifact management, and file system access.
"""

import io
import json
import mimetypes
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

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import MessageType
from onyx.db.enums import SandboxStatus
from onyx.db.llm import fetch_default_llm_model
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.llm.factory import get_default_llm
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import FileSystemEntry
from onyx.server.features.build.api.packet_logger import get_packet_logger
from onyx.server.features.build.api.packet_logger import log_separator
from onyx.server.features.build.api.packets import BuildPacket
from onyx.server.features.build.api.packets import ErrorPacket
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.configs import MAX_TOTAL_UPLOAD_SIZE_BYTES
from onyx.server.features.build.configs import MAX_UPLOAD_FILES_PER_SESSION
from onyx.server.features.build.configs import PERSISTENT_DOCUMENT_STORAGE_PATH
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.db.build_session import create_build_session__no_commit
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import delete_build_session__no_commit
from onyx.server.features.build.db.build_session import (
    fetch_llm_provider_by_type_for_build_mode,
)
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import get_empty_session_for_user
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import get_user_build_sessions
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.build_session import upsert_agent_plan
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import get_running_sandbox_count_by_tenant
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox import get_sandbox_manager
from onyx.server.features.build.sandbox.kubernetes.internal.acp_exec_client import (
    SSEKeepalive,
)
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.session.prompts import BUILD_NAMING_SYSTEM_PROMPT
from onyx.server.features.build.session.prompts import BUILD_NAMING_USER_PROMPT
from onyx.server.features.build.session.prompts import (
    FOLLOWUP_SUGGESTIONS_SYSTEM_PROMPT,
)
from onyx.server.features.build.session.prompts import FOLLOWUP_SUGGESTIONS_USER_PROMPT
from onyx.tracing.framework.create import ensure_trace
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_span_output
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


class UploadLimitExceededError(ValueError):
    """Raised when file upload limits are exceeded."""


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


# Hidden directories/files to filter from listings
HIDDEN_PATTERNS = {
    ".venv",
    ".git",
    ".next",
    "__pycache__",
    "node_modules",
    ".DS_Store",
    "opencode.json",
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
    # LLM Configuration
    # =========================================================================

    def _get_llm_config(
        self,
        requested_provider_type: str | None,
        requested_model_name: str | None,
    ) -> LLMProviderConfig:
        """Get LLM config for sandbox provisioning.

        Resolution priority:
        1. User's requested provider/model (from cookie)
        2. System default provider

        Args:
            requested_provider_type: Provider type from user's cookie (e.g., "anthropic", "openai")
            requested_model_name: Model name from user's cookie (e.g., "claude-opus-4-5")

        Returns:
            LLMProviderConfig for sandbox provisioning

        Raises:
            ValueError: If no LLM provider is configured
        """
        if requested_provider_type and requested_model_name:
            # Look up provider by type (e.g., "anthropic", "openai", "openrouter")
            provider = fetch_llm_provider_by_type_for_build_mode(
                self._db_session, requested_provider_type
            )
            if provider:
                # Use the requested model directly - the provider's API will
                # reject invalid models. This allows users to use models that
                # aren't explicitly configured as "visible" in the admin UI.
                return LLMProviderConfig(
                    provider=provider.provider,
                    model_name=requested_model_name,
                    api_key=provider.api_key,
                    api_base=provider.api_base,
                )
            else:
                logger.warning(
                    f"Requested provider type {requested_provider_type} not found, "
                    f"falling back to default"
                )

        # Fallback to system default
        default_model = fetch_default_llm_model(self._db_session)
        if not default_model:
            raise ValueError("No default LLM model found")

        return LLMProviderConfig(
            provider=default_model.llm_provider.provider,
            model_name=default_model.name,
            api_key=default_model.llm_provider.api_key,
            api_base=default_model.llm_provider.api_base,
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
        user_work_area: str | None = None,
        user_level: str | None = None,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
        demo_data_enabled: bool = True,
    ) -> BuildSession:
        """
        Create a new build session with a sandbox.

        NOTE: This method does NOT commit the transaction. The caller is
        responsible for committing after this method returns successfully.
        This allows the entire operation to be atomic at the endpoint level.

        Args:
            user_id: The user ID
            name: Optional session name
            user_work_area: User's work area for demo persona (e.g., "engineering")
            user_level: User's level for demo persona (e.g., "ic", "manager")
            llm_provider_type: Provider type from user's cookie (e.g., "anthropic", "openai")
            llm_model_name: Model name from user's cookie (e.g., "claude-opus-4-5")
            demo_data_enabled: Explicit flag for demo data mode. Defaults to True if not provided.

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

        # Get LLM config (uses user's selection or falls back to default)
        llm_config = self._get_llm_config(llm_provider_type, llm_model_name)

        # Build tenant/user-specific path for FILE_SYSTEM documents (sandbox isolation)
        # Each user's sandbox can only access documents they created
        # Path structure: {base_path}/{tenant_id}/knowledge/{user_id}/
        # This matches the path structure used by PersistentDocumentWriter
        if PERSISTENT_DOCUMENT_STORAGE_PATH:
            user_file_system_path = str(
                Path(PERSISTENT_DOCUMENT_STORAGE_PATH)
                / tenant_id
                / "knowledge"
                / str(user_id)
            )
        else:
            # Fallback for local development without persistent storage
            user_file_system_path = "/tmp/onyx-files"

        # Ensure the user's document directory exists (if local)
        if SANDBOX_BACKEND == SandboxBackend.LOCAL:
            Path(user_file_system_path).mkdir(parents=True, exist_ok=True)

        # Allocate port for this session (per-session port allocation)
        # Both LOCAL and KUBERNETES backends use the same port allocation strategy
        nextjs_port = allocate_nextjs_port(self._db_session)

        # Create BuildSession record with allocated port (uses flush, caller commits)
        build_session = create_build_session__no_commit(
            user_id, self._db_session, name=name, demo_data_enabled=demo_data_enabled
        )
        build_session.nextjs_port = nextjs_port
        self._db_session.flush()
        session_id = str(build_session.id)
        logger.info(
            f"Created build session {session_id} for user {user_id} "
            f"(port: {nextjs_port})"
        )

        # Check if user already has a sandbox (one sandbox per user model)
        existing_sandbox = get_sandbox_by_user_id(self._db_session, user_id)

        if existing_sandbox:
            # User already has a sandbox - check if it needs re-provisioning
            sandbox = existing_sandbox
            sandbox_id = sandbox.id

            if sandbox.status in (
                SandboxStatus.TERMINATED,
                SandboxStatus.SLEEPING,
                SandboxStatus.FAILED,
            ):
                # Re-provision sandbox (pod doesn't exist or failed)
                logger.info(
                    f"Re-provisioning {sandbox.status.value} sandbox {sandbox_id} "
                    f"for user {user_id}"
                )
                sandbox_info = self._sandbox_manager.provision(
                    sandbox_id=sandbox_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    llm_config=llm_config,
                )
                # Use update function to also set heartbeat when transitioning to RUNNING
                update_sandbox_status__no_commit(
                    self._db_session, sandbox_id, sandbox_info.status
                )
            elif sandbox.status.is_active():
                # Verify pod is healthy before reusing (use short timeout for quick check)
                if not self._sandbox_manager.health_check(sandbox_id, timeout=5.0):
                    logger.warning(
                        f"Sandbox {sandbox_id} marked as {sandbox.status} but pod is "
                        f"unhealthy/missing. Entering recovery mode."
                    )
                    # Terminate to clean up any lingering K8s resources
                    self._sandbox_manager.terminate(sandbox_id)

                    # Mark as terminated and re-provision
                    update_sandbox_status__no_commit(
                        self._db_session, sandbox_id, SandboxStatus.TERMINATED
                    )

                    logger.info(
                        f"Re-provisioning sandbox {sandbox_id} for user {user_id}"
                    )
                    sandbox_info = self._sandbox_manager.provision(
                        sandbox_id=sandbox_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        llm_config=llm_config,
                    )
                    # Use update function to also set heartbeat when transitioning to RUNNING
                    update_sandbox_status__no_commit(
                        self._db_session, sandbox_id, sandbox_info.status
                    )
                else:
                    logger.info(
                        f"Reusing existing sandbox {sandbox_id} (status: {sandbox.status}) "
                        f"for new session {session_id}"
                    )
            else:
                # PROVISIONING status - sandbox is being created by another request
                # Just fail this request
                msg = (
                    f"Sandbox {sandbox_id} has status {sandbox.status.value} and is being "
                    f"created by another request for new session {session_id}"
                )
                logger.error(msg)
                raise RuntimeError(msg)
        else:
            # Create new Sandbox record for the user (uses flush, caller commits)
            sandbox = create_sandbox__no_commit(
                db_session=self._db_session,
                user_id=user_id,
            )
            sandbox_id = sandbox.id
            logger.info(f"Created sandbox record {sandbox_id} for session {session_id}")

            # Provision sandbox (no DB operations inside)
            sandbox_info = self._sandbox_manager.provision(
                sandbox_id=sandbox_id,
                user_id=user_id,
                tenant_id=tenant_id,
                llm_config=llm_config,
            )

            # Update sandbox status (also refreshes heartbeat when transitioning to RUNNING)
            update_sandbox_status__no_commit(
                self._db_session, sandbox_id, sandbox_info.status
            )

        # Set up session workspace within the sandbox
        logger.info(
            f"Setting up session workspace {session_id} in sandbox {sandbox.id}"
        )
        # Fetch user data for personalization in AGENTS.md
        user = fetch_user_by_id(self._db_session, user_id)
        user_name = user.personal_name if user else None
        user_role = user.personal_role if user else None

        self._sandbox_manager.setup_session_workspace(
            sandbox_id=sandbox.id,
            session_id=build_session.id,
            llm_config=llm_config,
            nextjs_port=nextjs_port,
            file_system_path=user_file_system_path,
            snapshot_path=None,  # TODO: Support restoring from snapshot
            user_name=user_name,
            user_role=user_role,
            user_work_area=user_work_area,
            user_level=user_level,
            use_demo_data=demo_data_enabled,
        )
        sandbox_id = sandbox.id
        logger.info(
            f"Successfully created session {session_id} with workspace in sandbox {sandbox.id}"
        )

        return build_session

    def get_or_create_empty_session(
        self,
        user_id: UUID,
        user_work_area: str | None = None,
        user_level: str | None = None,
        llm_provider_type: str | None = None,
        llm_model_name: str | None = None,
        demo_data_enabled: bool = True,
    ) -> BuildSession:
        """Get existing empty session or create a new one with provisioned sandbox.

        Used for pre-provisioning sandboxes when user lands on /build/v1.
        Returns existing recent empty session if one exists, has a healthy sandbox,
        AND has matching demo_data_enabled setting. Otherwise creates new.
        If an empty session exists but its sandbox is unhealthy/terminated/missing,
        the stale session is deleted and a fresh one is created (which will handle
        sandbox recovery/re-provisioning).

        Args:
            user_id: The user ID
            user_work_area: User's work area for demo persona (e.g., "engineering")
            user_level: User's level for demo persona (e.g., "ic", "manager")
            llm_provider_type: Provider type from user's cookie (e.g., "anthropic", "openai")
            llm_model_name: Model name from user's cookie (e.g., "claude-opus-4-5")
            demo_data_enabled: Explicit flag for demo data mode. Defaults to True if not provided.

        Returns:
            BuildSession (existing empty or newly created)

        Raises:
            ValueError: If max concurrent sandboxes reached
            RuntimeError: If sandbox provisioning fails
        """
        # Look for existing empty session with matching demo_data setting
        existing = get_empty_session_for_user(
            user_id, self._db_session, demo_data_enabled=demo_data_enabled
        )
        if existing:
            logger.info(
                f"Existing empty session {existing.id} found for user {user_id}"
            )
            # Verify sandbox is healthy before returning existing session
            sandbox = get_sandbox_by_user_id(self._db_session, user_id)

            if sandbox and sandbox.status.is_active():
                # Quick health check to verify sandbox is actually responsive
                if self._sandbox_manager.health_check(sandbox.id, timeout=5.0):
                    logger.info(
                        f"Returning existing empty session {existing.id} for user {user_id}"
                    )
                    return existing
                else:
                    logger.warning(
                        f"Empty session {existing.id} has unhealthy sandbox {sandbox.id}. "
                        f"Deleting and creating fresh session."
                    )
            else:
                logger.warning(
                    f"Empty session {existing.id} has no active sandbox "
                    f"(sandbox={'missing' if not sandbox else sandbox.status}). "
                    f"Deleting and creating fresh session."
                )

            # Delete the stale empty session - create_session__no_commit will
            # handle sandbox recovery/re-provisioning
            delete_build_session__no_commit(existing.id, user_id, self._db_session)

        return self.create_session__no_commit(
            user_id=user_id,
            user_work_area=user_work_area,
            user_level=user_level,
            llm_provider_type=llm_provider_type,
            llm_model_name=llm_model_name,
            demo_data_enabled=demo_data_enabled,
        )

    def delete_empty_session(self, user_id: UUID) -> bool:
        """Delete user's pre-provisioned (empty) session if one exists.

        A session is considered "empty" if it has no messages.
        This is called when user changes LLM selection or toggles demo data
        so the session can be re-created with the new LLM configuration.

        Args:
            user_id: The user ID

        Returns:
            True if a session was deleted, False if none found
        """
        empty_session = get_empty_session_for_user(user_id, self._db_session)

        if not empty_session:
            logger.info(f"No empty session found for user {user_id}")
            return False

        session_id = empty_session.id

        # Get user's sandbox to clean up session workspace
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox and sandbox.status.is_active():
            try:
                self._sandbox_manager.cleanup_session_workspace(
                    sandbox_id=sandbox.id,
                    session_id=session_id,
                    nextjs_port=empty_session.nextjs_port,
                )
                logger.info(
                    f"Cleaned up session workspace {session_id} in sandbox {sandbox.id}"
                )
            except Exception as e:
                # Log but don't fail - session can still be deleted
                logger.warning(f"Failed to cleanup session workspace {session_id}: {e}")

        # Delete session (cascade deletes artifacts)
        delete_build_session__no_commit(session_id, user_id, self._db_session)
        logger.info(f"Deleted empty session {session_id} for user {user_id}")

        return True

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

        # Use LLM to generate a concise session name with Braintrust tracing
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
            with ensure_trace(
                "build_session_naming",
                group_id=str(session_id),
                metadata={"session_id": str(session_id)},
            ):
                with llm_generation_span(
                    llm=llm,
                    flow="build_session_naming",
                    input_messages=prompt_messages,
                ) as span_generation:
                    response = llm.invoke(
                        prompt_messages, reasoning_effort=ReasoningEffort.OFF
                    )
                    generated_name = llm_response_to_string(response).strip().strip('"')
                    record_llm_span_output(
                        span_generation, generated_name, response.usage
                    )

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

    def generate_followup_suggestions(
        self,
        user_message: str,
        assistant_message: str,
    ) -> list[dict[str, str]]:
        """
        Generate follow-up suggestions based on the first exchange.

        Args:
            user_message: The first user message content
            assistant_message: The first assistant response (text only, no tool calls)

        Returns:
            List of suggestion dicts with "theme" and "text" keys, or empty list on failure
        """
        if not user_message or not assistant_message:
            return []

        try:
            llm = get_default_llm()
            prompt_messages: LanguageModelInput = [
                SystemMessage(content=FOLLOWUP_SUGGESTIONS_SYSTEM_PROMPT),
                UserMessage(
                    content=FOLLOWUP_SUGGESTIONS_USER_PROMPT.format(
                        user_message=user_message[:1000],  # Limit input size
                        assistant_message=assistant_message[:2000],
                    )
                ),
            ]
            # Call LLM with Braintrust tracing
            with ensure_trace("build_followup_suggestions"):
                with llm_generation_span(
                    llm=llm,
                    flow="build_followup_suggestions",
                    input_messages=prompt_messages,
                ) as span_generation:
                    response = llm.invoke(
                        prompt_messages,
                        reasoning_effort=ReasoningEffort.OFF,
                        max_tokens=500,
                    )
                    raw_output = llm_response_to_string(response).strip()
                    record_llm_span_output(span_generation, raw_output, response.usage)

            return self._parse_suggestions(raw_output)
        except Exception as e:
            logger.warning(f"Failed to generate follow-up suggestions with LLM: {e}")
            return []

    def _parse_suggestions(self, raw_output: str) -> list[dict[str, str]]:
        """
        Parse suggestions from LLM output with multiple fallback strategies.

        Args:
            raw_output: Raw LLM response string

        Returns:
            List of suggestion dicts or empty list on parse failure
        """
        import re

        # Strategy 1: Try direct JSON parse
        try:
            # Strip common LLM artifacts (code fences, etc.)
            cleaned = raw_output.strip()
            if cleaned.startswith("```"):
                # Extract content between code fences
                parts = cleaned.split("```")
                if len(parts) >= 2:
                    cleaned = parts[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                    cleaned = cleaned.strip()

            data = json.loads(cleaned)
            if isinstance(data, list) and len(data) >= 2:
                suggestions = []
                for item in data[:2]:
                    if isinstance(item, dict) and "theme" in item and "text" in item:
                        theme = item["theme"].lower()
                        if theme in ("add", "question"):
                            text = str(item["text"])[:150]  # Truncate to max length
                            suggestions.append({"theme": theme, "text": text})
                if len(suggestions) == 2:
                    return suggestions
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Strategy 2: Regex extraction for common patterns
        # Handles: "theme": "add", "text": "..." patterns
        suggestions = []
        for theme in ["add", "question"]:
            # Match "theme": "add" followed by "text": "..."
            pattern = rf'"theme"\s*:\s*"{theme}"[^}}]*"text"\s*:\s*"([^"]+)"'
            match = re.search(pattern, raw_output, re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1)[:150]
                suggestions.append({"theme": theme, "text": text})

        if len(suggestions) == 2:
            return suggestions

        # Strategy 3: Alternative pattern - theme and text in any order
        suggestions = []
        for theme in ["add", "question"]:
            pattern = rf'"text"\s*:\s*"([^"]+)"[^}}]*"theme"\s*:\s*"{theme}"'
            match = re.search(pattern, raw_output, re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1)[:150]
                suggestions.append({"theme": theme, "text": text})

        if len(suggestions) == 2:
            return suggestions

        # Silent fail - return empty list
        logger.warning(
            f"Failed to parse suggestions from LLM output: {raw_output[:200]}"
        )
        return []

    def delete_session(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Delete a build session and all associated data.

        Cleans up session workspace but does NOT terminate the sandbox
        (sandbox is user-owned and shared across sessions).

        NOTE: This method does NOT commit the transaction. The caller is
        responsible for committing after this method returns successfully.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            True if deleted, False if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return False

        # Get user's sandbox to clean up session workspace
        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox and sandbox.status.is_active():
            # Clean up session workspace (but don't terminate sandbox)
            try:
                self._sandbox_manager.cleanup_session_workspace(
                    sandbox_id=sandbox.id,
                    session_id=session_id,
                    nextjs_port=session.nextjs_port,
                )
                logger.info(
                    f"Cleaned up session workspace {session_id} in sandbox {sandbox.id}"
                )
            except Exception as e:
                # Log but don't fail - session can still be deleted even if
                # workspace cleanup fails (e.g., if pod is already terminated)
                logger.warning(f"Failed to cleanup session workspace {session_id}: {e}")

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

        # The log file auto-rotates to keep only the last N lines (default 5000).
        # Add a prominent separator for visual identification of new message streams.
        log_separator(
            f"NEW MESSAGE STREAM - Session: {str(session_id)[:8]} - "
            f"User: {str(user_id)[:8]}"
        )
        packet_logger.log_raw(
            "STREAM-START",
            {
                "session_id": str(session_id),
                "user_id": str(user_id),
                "message_preview": user_message_content[:200]
                + ("..." if len(user_message_content) > 200 else ""),
            },
        )

        try:
            # Verify session exists and belongs to user
            session = get_build_session(session_id, user_id, self._db_session)
            if session is None:
                error_packet = ErrorPacket(message="Session not found")
                packet_logger.log("error", error_packet.model_dump())
                yield _format_packet_event(error_packet)
                return

            # Get the user's sandbox (now user-owned, not session-owned)
            sandbox = get_sandbox_by_user_id(self._db_session, user_id)

            # Check if sandbox is running
            if not sandbox or sandbox.status != SandboxStatus.RUNNING:
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
            events_emitted = 0

            packet_logger.log_raw(
                "STREAM-BEGIN-AGENT-LOOP",
                {
                    "session_id": str(session_id),
                    "sandbox_id": str(sandbox_id),
                    "turn_index": turn_index,
                },
            )

            # Stream ACP events directly to frontend
            for acp_event in self._sandbox_manager.send_message(
                sandbox_id, session_id, user_message_content
            ):
                # Handle SSE keepalive - send comment to keep connection alive
                if isinstance(acp_event, SSEKeepalive):
                    # SSE comments start with : and are ignored by EventSource
                    # but keep the HTTP connection alive
                    packet_logger.log_sse_emit("keepalive", session_id)
                    yield ": keepalive\n\n"
                    continue

                # Check if we need to finalize pending chunks before processing
                event_type = self._get_event_type(acp_event)
                if state.should_finalize_chunks(event_type):
                    _save_pending_chunks(state)

                events_emitted += 1

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
                    packet_logger.log_sse_emit("agent_message_chunk", session_id)
                    yield _serialize_acp_event(acp_event, "agent_message_chunk")

                elif isinstance(acp_event, AgentThoughtChunk):
                    text = _extract_text_from_content(acp_event.content)
                    if text:
                        state.add_thought_chunk(text)
                    packet_logger.log(
                        "agent_thought_chunk",
                        acp_event.model_dump(mode="json", by_alias=True),
                    )
                    packet_logger.log_sse_emit("agent_thought_chunk", session_id)
                    yield _serialize_acp_event(acp_event, "agent_thought_chunk")

                elif isinstance(acp_event, ToolCallStart):
                    # Stream to frontend but don't save - wait for completion
                    packet_logger.log(
                        "tool_call_start",
                        acp_event.model_dump(mode="json", by_alias=True),
                    )
                    packet_logger.log_sse_emit("tool_call_start", session_id)
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

                    # Log full event to packet logger (can handle large payloads)
                    packet_logger.log("tool_call_progress", event_data)
                    packet_logger.log_sse_emit("tool_call_progress", session_id)
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
                    packet_logger.log_sse_emit("agent_plan_update", session_id)
                    yield _serialize_acp_event(acp_event, "agent_plan_update")

                elif isinstance(acp_event, CurrentModeUpdate):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "current_mode_update"
                    packet_logger.log("current_mode_update", event_data)
                    packet_logger.log_sse_emit("current_mode_update", session_id)
                    yield _serialize_acp_event(acp_event, "current_mode_update")

                elif isinstance(acp_event, PromptResponse):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "prompt_response"
                    packet_logger.log("prompt_response", event_data)
                    packet_logger.log_sse_emit("prompt_response", session_id)
                    yield _serialize_acp_event(acp_event, "prompt_response")

                elif isinstance(acp_event, ACPError):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "error"
                    packet_logger.log("error", event_data)
                    packet_logger.log_sse_emit("error", session_id)
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

            # Log streaming completion
            packet_logger.log_raw(
                "STREAM-COMPLETE",
                {
                    "session_id": str(session_id),
                    "sandbox_id": str(sandbox_id),
                    "turn_index": turn_index,
                    "events_emitted": events_emitted,
                    "message_chunks_accumulated": len(state.message_chunks),
                    "thought_chunks_accumulated": len(state.thought_chunks),
                },
            )

            # Update heartbeat after successful message exchange
            update_sandbox_heartbeat(self._db_session, sandbox_id)

        except ValueError as e:
            error_packet = ErrorPacket(message=str(e))
            packet_logger.log("error", error_packet.model_dump())
            packet_logger.log_raw(
                "STREAM-ERROR",
                {
                    "session_id": str(session_id),
                    "error_type": "ValueError",
                    "error": str(e),
                },
            )
            logger.exception("ValueError in build message streaming")
            yield _format_packet_event(error_packet)
        except RuntimeError as e:
            error_packet = ErrorPacket(message=str(e))
            packet_logger.log("error", error_packet.model_dump())
            packet_logger.log_raw(
                "STREAM-ERROR",
                {
                    "session_id": str(session_id),
                    "error_type": "RuntimeError",
                    "error": str(e),
                },
            )
            logger.exception(f"RuntimeError in build message streaming: {e}")
            yield _format_packet_event(error_packet)
        except Exception as e:
            error_packet = ErrorPacket(message=str(e))
            packet_logger.log("error", error_packet.model_dump())
            packet_logger.log_raw(
                "STREAM-ERROR",
                {
                    "session_id": str(session_id),
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
            )
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

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return None

        artifacts: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        # Check for outputs directory using sandbox manager
        try:
            output_entries = self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path="outputs",
            )
        except ValueError:
            # Directory doesn't exist
            return artifacts

        # Check for webapp (web directory in outputs)
        has_webapp = any(
            entry.is_directory and entry.name == "web" for entry in output_entries
        )

        if has_webapp:
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
            path: Relative path to the artifact (within session workspace)

        Returns:
            Tuple of (content, mime_type, filename) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is a directory
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return None

        # Extract filename from path
        filename = Path(path).name

        # Filter out opencode.json files
        if filename == "opencode.json":
            return None

        # Use sandbox manager to read file (works for both local and K8s)
        try:
            content = self._sandbox_manager.read_file(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path=path,
            )
        except ValueError as e:
            # read_file raises ValueError for not found or directory
            if "Not a file" in str(e):
                raise ValueError("Cannot download directory")
            return None

        mime_type, _ = mimetypes.guess_type(filename)

        return (content, mime_type or "application/octet-stream", filename)

    def export_docx(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> tuple[bytes, str] | None:
        """
        Export a markdown file as DOCX.

        Reads the markdown file and converts it to DOCX using pypandoc.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the markdown file

        Returns:
            Tuple of (docx_bytes, filename) or None if not found

        Raises:
            ValueError: If path traversal attempted, file is not markdown, etc.
        """
        result = self.download_artifact(session_id, user_id, path)
        if result is None:
            return None

        content_bytes, _mime_type, filename = result

        if not filename.lower().endswith(".md"):
            raise ValueError("Only markdown (.md) files can be exported as DOCX")

        import tempfile
        import pypandoc  # type: ignore

        md_text = content_bytes.decode("utf-8")

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=True) as tmp:
            pypandoc.convert_text(md_text, "docx", format="md", outputfile=tmp.name)
            docx_bytes = tmp.read()

        docx_filename = filename.rsplit(".", 1)[0] + ".docx"
        return (docx_bytes, docx_filename)

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

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return {"has_webapp": False, "webapp_url": None, "status": "no_sandbox"}

        # Return the proxy URL - the proxy handles routing to the correct sandbox
        # for both local and Kubernetes environments
        webapp_url = None
        if session.nextjs_port:
            webapp_url = f"{WEB_DOMAIN}/api/build/sessions/{session_id}/webapp"

        return {
            "has_webapp": session.nextjs_port is not None,
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

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return None

        # Check if web directory exists using sandbox manager
        try:
            self._sandbox_manager.list_directory(
                sandbox_id=sandbox.id,
                session_id=session_id,
                path="outputs/web",
            )
        except ValueError:
            # Directory doesn't exist
            return None

        # Recursively collect all files in the web directory
        def collect_files(dir_path: str) -> list[tuple[str, str]]:
            """Collect all files recursively, returning (full_path, relative_path) tuples."""
            files: list[tuple[str, str]] = []
            try:
                entries = self._sandbox_manager.list_directory(
                    sandbox_id=sandbox.id,
                    session_id=session_id,
                    path=dir_path,
                )
                for entry in entries:
                    if entry.is_directory:
                        # Recursively collect files from subdirectory
                        files.extend(collect_files(entry.path))
                    else:
                        # entry.path is relative to session root (e.g., "outputs/web/file.txt")
                        # arcname should be relative to web dir (e.g., "file.txt")
                        arcname = entry.path.replace("outputs/web/", "", 1)
                        files.append((entry.path, arcname))
            except ValueError:
                pass  # Directory doesn't exist, skip
            return files

        file_list = collect_files("outputs/web")

        # Create zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for full_path, arcname in file_list:
                try:
                    content = self._sandbox_manager.read_file(
                        sandbox_id=sandbox.id,
                        session_id=session_id,
                        path=full_path,
                    )
                    zip_file.writestr(arcname, content)
                except ValueError:
                    # Skip files that can't be read
                    pass

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
        List files and directories in the session workspace.

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path from session workspace root (empty string for root)

        Returns:
            DirectoryListing with sorted entries (directories first) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return None

        # Use sandbox manager to list directory (works for both local and K8s)
        raw_entries = self._sandbox_manager.list_directory(
            sandbox_id=sandbox.id,
            session_id=session_id,
            path=path,
        )

        # Filter hidden files and directories
        entries: list[FileSystemEntry] = [
            entry
            for entry in raw_entries
            if entry.name not in HIDDEN_PATTERNS and not entry.name.startswith(".")
        ]

        # Sort: directories first, then files, both alphabetically
        entries.sort(key=lambda e: (not e.is_directory, e.name.lower()))

        return DirectoryListing(path=path, entries=entries)

    def get_upload_stats(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> tuple[int, int]:
        """Get current file count and total size for a session's uploads.

        Delegates to SandboxManager for the actual filesystem query (supports both
        local filesystem and Kubernetes pods).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership

        Returns:
            Tuple of (file_count, total_size_bytes)

        Raises:
            ValueError: If session not found
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")

        # Delegate to sandbox manager (handles both local and K8s)
        return self._sandbox_manager.get_upload_stats(
            sandbox_id=sandbox.id,
            session_id=session_id,
        )

    def upload_file(
        self,
        session_id: UUID,
        user_id: UUID,
        filename: str,
        content: bytes,
    ) -> tuple[str, int]:
        """Upload a file to the session's workspace.

        Delegates to SandboxManager for the actual file write (supports both
        local filesystem and Kubernetes pods).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            filename: Sanitized filename (validation done at API layer)
            content: File content as bytes

        Returns:
            Tuple of (relative_path, size_bytes) where the file was saved

        Raises:
            ValueError: If session not found or upload limits exceeded
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")

        # Check upload limits
        file_count, total_size = self.get_upload_stats(session_id, user_id)

        if file_count >= MAX_UPLOAD_FILES_PER_SESSION:
            raise UploadLimitExceededError(
                f"Maximum number of files ({MAX_UPLOAD_FILES_PER_SESSION}) reached"
            )

        if total_size + len(content) > MAX_TOTAL_UPLOAD_SIZE_BYTES:
            max_mb = MAX_TOTAL_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise UploadLimitExceededError(
                f"Total upload size limit ({max_mb}MB) exceeded"
            )

        # Delegate to sandbox manager (handles both local and K8s)
        relative_path = self._sandbox_manager.upload_file(
            sandbox_id=sandbox.id,
            session_id=session_id,
            filename=filename,
            content=content,
        )

        # Update heartbeat - file upload is user activity that keeps sandbox alive
        update_sandbox_heartbeat(self._db_session, sandbox.id)

        return relative_path, len(content)

    def delete_file(
        self,
        session_id: UUID,
        user_id: UUID,
        path: str,
    ) -> bool:
        """Delete a file from the session's workspace.

        Delegates to SandboxManager for the actual file delete (supports both
        local filesystem and Kubernetes pods).

        Args:
            session_id: The session UUID
            user_id: The user ID to verify ownership
            path: Relative path to the file (e.g., "attachments/doc.pdf")

        Returns:
            True if file was deleted, False if not found

        Raises:
            ValueError: If session not found or path traversal attempted
        """
        # Verify session ownership
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            raise ValueError("Session not found")

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            raise ValueError("Sandbox not found")

        # Delegate to sandbox manager (handles both local and K8s)
        deleted = self._sandbox_manager.delete_file(
            sandbox_id=sandbox.id,
            session_id=session_id,
            path=path,
        )

        if deleted:
            # SandboxManager already logs the deletion details
            # Update heartbeat - file deletion is user activity that keeps sandbox alive
            update_sandbox_heartbeat(self._db_session, sandbox.id)

        return deleted

    # =========================================================================
    # Sandbox Management Operations
    # =========================================================================

    def terminate_user_sandbox(self, user_id: UUID) -> bool:
        """Terminate the user's sandbox and clean up all session workspaces.

        Used for explicit "start fresh" functionality.

        Args:
            user_id: The user ID

        Returns:
            True if sandbox was terminated, False if user had no sandbox
        """
        from onyx.server.features.build.db.sandbox import (
            update_sandbox_status__no_commit,
        )

        sandbox = get_sandbox_by_user_id(self._db_session, user_id)
        if sandbox is None:
            return False

        if sandbox.status == SandboxStatus.TERMINATED:
            logger.info(f"Sandbox {sandbox.id} already terminated")
            return True

        try:
            # Terminate the sandbox (this cleans up all resources)
            self._sandbox_manager.terminate(sandbox.id)
            logger.info(f"Terminated sandbox {sandbox.id} for user {user_id}")

            # Update status in database
            update_sandbox_status__no_commit(
                self._db_session, sandbox.id, SandboxStatus.TERMINATED
            )
            self._db_session.flush()

            return True

        except Exception as e:
            logger.error(f"Failed to terminate sandbox {sandbox.id}: {e}")
            raise RuntimeError(f"Failed to terminate sandbox: {e}") from e
