"""Public interface for session operations.

SessionManager is the main entry point for build session lifecycle management.
It orchestrates session CRUD, message handling, artifact management, and file system access.
"""

import json
import mimetypes
import os
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
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import User
from onyx.server.features.build.api.models import ArtifactInfo
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import FileSystemEntry
from onyx.server.features.build.api.packets import ArtifactCreatedPacket
from onyx.server.features.build.api.packets import ArtifactType
from onyx.server.features.build.api.packets import BuildPacket
from onyx.server.features.build.api.packets import create_artifact_from_file
from onyx.server.features.build.api.packets import ErrorPacket
from onyx.server.features.build.api.packets import FileWritePacket
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.configs import PERSISTENT_DOCUMENT_STORAGE_PATH
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.db.build_session import create_build_session
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import delete_build_session
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import get_user_build_sessions
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.sandbox.manager import get_sandbox_manager
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


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
        reset_timestamp: datetime | None = None,
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

    def __init__(self, db_session: Session) -> None:
        """Initialize the SessionManager with a database session.

        Args:
            db_session: The SQLAlchemy database session to use for all operations
        """
        self._db_session = db_session
        self._sandbox_manager = get_sandbox_manager()

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def check_rate_limit(self, user: User | None) -> None:
        """
        Check build mode rate limits for a user.

        Args:
            user: The user to check rate limits for

        Raises:
            RateLimitError: If rate limit is exceeded
        """
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

    def create_session(
        self,
        user_id: UUID,
        name: str | None = None,
    ) -> BuildSession:
        """
        Create a new build session with a sandbox.

        Args:
            user_id: The user ID
            name: Optional session name

        Returns:
            The created BuildSession model

        Raises:
            ValueError: If max concurrent sandboxes reached
            RuntimeError: If sandbox provisioning fails
        """
        tenant_id = get_current_tenant_id()

        # Create BuildSession record first (required for Sandbox foreign key)
        build_session = create_build_session(user_id, self._db_session, name=name)
        session_id = str(build_session.id)
        logger.info(f"Created build session {session_id} for user {user_id}")

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

        # Provision sandbox
        self._sandbox_manager.provision(
            session_id=session_id,
            tenant_id=tenant_id,
            file_system_path=user_file_system_path,
            db_session=self._db_session,
        )

        # Refresh to get the created sandbox
        self._db_session.refresh(build_session)
        return build_session

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

    def update_session_name(
        self,
        session_id: UUID,
        user_id: UUID,
        name: str,
    ) -> BuildSession | None:
        """
        Update the name of a build session.

        Args:
            session_id: The session UUID
            user_id: The user ID
            name: The new session name

        Returns:
            Updated BuildSession model or None if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return None

        session.name = name
        self._db_session.commit()
        self._db_session.refresh(session)
        return session

    def delete_session(
        self,
        session_id: UUID,
        user_id: UUID,
    ) -> bool:
        """
        Delete a build session and all associated data.

        Terminates any running sandbox before deletion.

        Args:
            session_id: The session UUID
            user_id: The user ID

        Returns:
            True if deleted, False if not found
        """
        session = get_build_session(session_id, user_id, self._db_session)
        if session is None:
            return False

        # Terminate sandbox if running
        if session.sandbox and session.sandbox.status in [
            SandboxStatus.RUNNING,
            SandboxStatus.PROVISIONING,
        ]:
            logger.info(f"Terminating sandbox before deleting session {session_id}")
            self._sandbox_manager.terminate(str(session.sandbox.id), self._db_session)

        return delete_build_session(session_id, user_id, self._db_session)

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
        The assistant's response is accumulated during streaming and saved to the
        database only AFTER the full response is generated.
        """
        # Accumulate assistant message content
        assistant_message_parts: list[str] = []

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

        def _save_acp_event_to_db(event_type: str, event_data: dict[str, Any]) -> None:
            """Save an ACP event as a separate message in the database."""
            if event_type in [
                "tool_call_start",
                "tool_call_progress",
                "agent_thought_chunk",
                "agent_plan_update",
            ]:
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    content="",
                    db_session=self._db_session,
                    message_metadata=event_data,
                )

        try:
            logger.warning(f"[STREAM] Starting stream for session {session_id}")
            # Verify session exists and belongs to user
            logger.warning(f"[STREAM] Verifying session {session_id} exists")
            session = get_build_session(session_id, user_id, self._db_session)
            if session is None:
                logger.warning(f"[STREAM] Session {session_id} not found")
                yield _format_packet_event(ErrorPacket(message="Session not found"))
                return

            # Check if sandbox is running
            logger.warning(f"[STREAM] Checking sandbox status for session {session_id}")
            if not session.sandbox or session.sandbox.status != SandboxStatus.RUNNING:
                logger.warning(f"[STREAM] Sandbox not running for session {session_id}")
                yield _format_packet_event(
                    ErrorPacket(
                        message="Sandbox is not running. Please wait for it to start."
                    )
                )
                return

            # Update last activity timestamp
            update_session_activity(session_id, self._db_session)

            # Save user message to database
            logger.warning(
                f"[STREAM] Saving user message to DB for session {session_id}"
            )
            user_message = create_message(
                session_id=session_id,
                message_type=MessageType.USER,
                content=user_message_content,
                db_session=self._db_session,
            )
            logger.warning(f"[STREAM] User message {user_message.id} saved")

            # Get sandbox
            sandbox = get_sandbox_by_session_id(self._db_session, session_id)
            if sandbox is None:
                logger.warning(f"[STREAM] Sandbox not found for session {session_id}")
                yield _format_packet_event(ErrorPacket(message="Sandbox not found"))
                return

            sandbox_id = str(sandbox.id)
            logger.warning(
                f"[STREAM] Found sandbox {sandbox_id} for session {session_id}"
            )

            logger.warning(
                f"[STREAM] Starting to stream ACP events from sandbox {sandbox_id}"
            )

            # Stream ACP events directly to frontend
            event_count = 0
            for acp_event in self._sandbox_manager.send_message(
                sandbox_id, user_message_content, self._db_session
            ):
                event_count += 1
                event_type = type(acp_event).__name__

                # Log full ACP event structure for debugging
                try:
                    if hasattr(acp_event, "model_dump"):
                        event_data = acp_event.model_dump(
                            mode="json", by_alias=True, exclude_none=True
                        )
                        logger.warning(
                            f"[STREAM] Event #{event_count}: {event_type} = {json.dumps(event_data, default=str)[:500]}"
                        )
                    else:
                        logger.warning(
                            f"[STREAM] Event #{event_count}: {event_type} = {str(acp_event)[:500]}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[STREAM] Event #{event_count}: {event_type} (failed to serialize: {e})"
                    )

                # Pass through ACP events with snake_case type names
                if isinstance(acp_event, AgentMessageChunk):
                    text = _extract_text_from_content(acp_event.content)
                    if text:
                        assistant_message_parts.append(text)
                    yield _serialize_acp_event(acp_event, "agent_message_chunk")

                elif isinstance(acp_event, AgentThoughtChunk):
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "agent_thought_chunk"
                    _save_acp_event_to_db("agent_thought_chunk", event_data)
                    yield _serialize_acp_event(acp_event, "agent_thought_chunk")

                elif isinstance(acp_event, ToolCallStart):
                    logger.warning(
                        f"[STREAM] Tool started: {acp_event.kind} - {acp_event.title}"
                    )
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "tool_call_start"
                    _save_acp_event_to_db("tool_call_start", event_data)
                    yield _serialize_acp_event(acp_event, "tool_call_start")

                elif isinstance(acp_event, ToolCallProgress):
                    logger.warning(
                        f"[STREAM] Tool progress: {acp_event.kind} - {acp_event.status}"
                    )
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "tool_call_progress"
                    _save_acp_event_to_db("tool_call_progress", event_data)
                    yield _serialize_acp_event(acp_event, "tool_call_progress")

                    # Emit file_write packet for write/edit operations
                    if acp_event.kind and acp_event.kind.lower() in [
                        "write",
                        "write_file",
                        "edit",
                    ]:
                        file_path = "outputs/file"
                        if hasattr(acp_event, "content") and acp_event.content:
                            for item in (
                                acp_event.content
                                if isinstance(acp_event.content, list)
                                else [acp_event.content]
                            ):
                                if hasattr(item, "text") and item.text:
                                    if "/" in item.text or "\\" in item.text:
                                        file_path = item.text.split("\n")[0][:200]
                                        break
                        file_write_packet = FileWritePacket(
                            path=file_path,
                            size_bytes=0,
                        )
                        logger.warning(f"[STREAM] File write detected: {file_path}")
                        yield _format_packet_event(file_write_packet)

                elif isinstance(acp_event, AgentPlanUpdate):
                    logger.warning("[STREAM] Plan update received")
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "agent_plan_update"
                    _save_acp_event_to_db("agent_plan_update", event_data)
                    yield _serialize_acp_event(acp_event, "agent_plan_update")

                elif isinstance(acp_event, CurrentModeUpdate):
                    logger.warning(f"[STREAM] Mode update: {acp_event.current_mode_id}")
                    yield _serialize_acp_event(acp_event, "current_mode_update")

                elif isinstance(acp_event, PromptResponse):
                    logger.warning(f"[STREAM] Agent finished: {acp_event.stop_reason}")
                    yield _serialize_acp_event(acp_event, "prompt_response")

                elif isinstance(acp_event, ACPError):
                    logger.warning(f"[STREAM] ACP Error: {acp_event.message}")
                    yield _serialize_acp_event(acp_event, "error")

                else:
                    logger.warning(f"[STREAM] Unhandled event type: {event_type}")

            logger.warning(f"[STREAM] Finished processing {event_count} ACP events")

            # Check for artifacts and emit artifact_created events
            logger.warning(f"[STREAM] Checking for artifacts in sandbox {sandbox_id}")
            sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox_id)
            outputs_dir = sandbox_path / "outputs"

            if outputs_dir.exists():
                logger.warning(f"[STREAM] Outputs directory exists: {outputs_dir}")
                web_dir = outputs_dir / "web"
                if web_dir.exists():
                    logger.warning(
                        f"[STREAM] Web app found at {web_dir}, creating artifact"
                    )
                    artifact = create_artifact_from_file(
                        session_id=session_id,
                        file_path="outputs/web/",
                        artifact_type=ArtifactType.WEB_APP,
                        name="Web Application",
                    )
                    yield _format_packet_event(ArtifactCreatedPacket(artifact=artifact))
                    logger.warning("[STREAM] Web app artifact created and emitted")
                else:
                    logger.warning(f"[STREAM] No web directory found at {web_dir}")
            else:
                logger.warning(
                    f"[STREAM] Outputs directory does not exist: {outputs_dir}"
                )

            # Save the complete assistant response to database
            if assistant_message_parts:
                total_chars = len("".join(assistant_message_parts))
                logger.warning(
                    f"[STREAM] Saving assistant response ({total_chars} chars) to DB"
                )
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    content="".join(assistant_message_parts),
                    db_session=self._db_session,
                )
                logger.warning(
                    f"[STREAM] Assistant response saved for session {session_id}"
                )
            else:
                logger.warning("[STREAM] No assistant message parts to save")

        except ValueError as e:
            logger.warning(f"[STREAM] ValueError executing task: {e}")
            logger.error(f"Error executing task: {e}")
            yield _format_packet_event(ErrorPacket(message=str(e)))
        except RuntimeError as e:
            logger.warning(f"[STREAM] RuntimeError in agent communication: {e}")
            logger.error(f"Agent communication error: {e}")
            yield _format_packet_event(ErrorPacket(message=str(e)))
        except Exception as e:
            logger.warning(f"[STREAM] Exception in build message streaming: {e}")
            logger.exception("Error in build message streaming")
            yield _format_packet_event(ErrorPacket(message=str(e)))
        finally:
            logger.warning(
                f"[STREAM] Stream generator finished for session {session_id}"
            )
            logger.debug(f"Stream generator finished for session {session_id}")

    # =========================================================================
    # Artifact Operations
    # =========================================================================

    def list_artifacts(
        self,
        session_id: UUID,
    ) -> list[ArtifactInfo] | None:
        """
        List artifacts generated in a session.

        Args:
            session_id: The session UUID

        Returns:
            List of ArtifactInfo or None if session not found
        """
        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)
        artifacts: list[ArtifactInfo] = []
        output_dir = sandbox_path / "outputs"

        if not output_dir.exists():
            return artifacts

        # Check for webapp
        web_dir = output_dir / "web"
        if web_dir.exists():
            artifacts.append(
                ArtifactInfo(
                    artifact_type="webapp",
                    path="outputs/web",
                    filename="webapp",
                    mime_type="application/x-directory",
                )
            )

        # Scan for other generated files
        for root, _, files in os.walk(output_dir):
            for filename in files:
                if filename.startswith(".") or filename in (
                    "package.json",
                    "package-lock.json",
                    "tsconfig.json",
                ):
                    continue

                file_path = Path(root) / filename
                rel_path = file_path.relative_to(sandbox_path)
                mime_type, _ = mimetypes.guess_type(str(file_path))

                if mime_type and mime_type.startswith("image/"):
                    artifact_type = "image"
                elif filename.endswith(".md"):
                    artifact_type = "markdown"
                else:
                    artifact_type = "file"

                artifacts.append(
                    ArtifactInfo(
                        artifact_type=artifact_type,
                        path=str(rel_path),
                        filename=filename,
                        mime_type=mime_type,
                    )
                )

        return artifacts

    def download_artifact(
        self,
        session_id: UUID,
        path: str,
    ) -> tuple[bytes, str, str] | None:
        """
        Download a specific artifact file.

        Args:
            session_id: The session UUID
            path: Relative path to the artifact

        Returns:
            Tuple of (content, mime_type, filename) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is a directory
        """
        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)
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
            return None

        if file_path.is_dir():
            raise ValueError("Cannot download directory")

        content = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(file_path))

        return (content, mime_type or "application/octet-stream", file_path.name)

    # =========================================================================
    # File System Operations
    # =========================================================================

    def list_directory(
        self,
        session_id: UUID,
        path: str,
    ) -> DirectoryListing | None:
        """
        List files and directories in the sandbox.

        Args:
            session_id: The session UUID
            path: Relative path from sandbox root (empty string for root)

        Returns:
            DirectoryListing with sorted entries (directories first) or None if not found

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        sandbox = get_sandbox_by_session_id(self._db_session, session_id)
        if sandbox is None:
            return None

        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.session_id)
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
