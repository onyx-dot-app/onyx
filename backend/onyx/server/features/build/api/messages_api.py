"""API endpoints for Build Mode message management."""

import json
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
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import MessageType
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.server.features.build.api.models import MessageListResponse
from onyx.server.features.build.api.models import MessageRequest
from onyx.server.features.build.api.models import MessageResponse
from onyx.server.features.build.api.packets import ArtifactCreatedPacket
from onyx.server.features.build.api.packets import ArtifactType
from onyx.server.features.build.api.packets import BuildPacket
from onyx.server.features.build.api.packets import create_artifact_from_file
from onyx.server.features.build.api.packets import ErrorPacket
from onyx.server.features.build.api.packets import FileWritePacket
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.build_session import update_session_activity
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter()


def check_build_rate_limits(
    user: User | None = Depends(current_user),
) -> None:
    """
    Dependency to check build mode rate limits before processing the request.

    Raises HTTPException(429) if rate limit is exceeded.
    Follows the same pattern as chat's check_token_rate_limits.
    """

    # Create a temporary session just for rate limit check
    with get_session_with_current_tenant() as db_session:
        rate_limit_status = get_user_rate_limit_status(user, db_session)
        if rate_limit_status.is_limited:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded. You have used "
                    f"{rate_limit_status.messages_used}/{rate_limit_status.limit} messages. "
                    f"Limit resets at {rate_limit_status.reset_timestamp}."
                    if rate_limit_status.reset_timestamp
                    else "This is a lifetime limit."
                ),
            )


@router.get("/sessions/{session_id}/messages", tags=PUBLIC_API_TAGS)
def list_messages(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageListResponse:
    """Get all messages for a build session."""
    user_id = user.id if user is not None else None

    # Verify session exists and belongs to user
    session = get_build_session(session_id, user_id, db_session)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get all messages
    messages = get_session_messages(session_id, db_session)

    return MessageListResponse(
        messages=[MessageResponse.from_model(msg) for msg in messages]
    )


async def stream_cli_agent_response(
    session_id: UUID,
    user_message_content: str,
    user_id: int | None,
):
    """
    Stream the CLI agent's response using SSE format.

    Executes the agent via SandboxManager and streams events back to the client.
    The assistant's response is accumulated during streaming and saved to the
    database only AFTER the full response is generated.

    Frontend-expected packet types (all use event: message):
    - step_start: Begin a logical step
    - step_delta: Progress within a step (from AgentThoughtChunk)
    - step_end: Finish a step
    - tool_start: Agent invoking a tool (from ToolCallStart)
    - tool_end: Tool execution finished (from ToolCallProgress)
    - file_write: File written to sandbox
    - plan: Agent's execution plan (from AgentPlanUpdate)
    - mode_update: Agent mode change (from CurrentModeUpdate)
    - artifact_created: New artifact generated

    ACP Events are passed through with their original type names:
    - agent_message_chunk: Text/image content from agent
    - agent_thought_chunk: Agent's internal reasoning
    - tool_call_start: Tool invocation started
    - tool_call_progress: Tool execution progress/result
    - agent_plan_update: Agent's execution plan
    - current_mode_update: Agent mode change
    - prompt_response: Agent finished processing
    - error: An error occurred
    """
    # Accumulate assistant message content
    assistant_message_parts: list[str] = []

    def _serialize_acp_event(event: Any, event_type: str) -> str:
        """Serialize an ACP event to SSE format, preserving ALL ACP data."""
        # Convert Pydantic model to dict, handling nested models
        # IMPORTANT: exclude_none=False to capture ALL fields from ACP
        if hasattr(event, "model_dump"):
            data = event.model_dump(mode="json", by_alias=True, exclude_none=False)
        else:
            data = {"raw": str(event)}

        # Add type field for frontend routing
        data["type"] = event_type

        # Add timestamp for frontend tracking
        data["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

        return f"event: message\ndata: {json.dumps(data)}\n\n"

    def _format_packet_event(packet: BuildPacket) -> str:
        """Format a BuildPacket as SSE."""
        return f"event: message\ndata: {packet.model_dump_json(by_alias=True)}\n\n"

    def _extract_text_from_content(content: Any) -> str:
        """Extract text from ACP content structure."""
        if content is None:
            return ""
        # Handle single content block
        if hasattr(content, "type") and content.type == "text":
            return getattr(content, "text", "") or ""
        # Handle array of content blocks
        if isinstance(content, list):
            texts = []
            for block in content:
                if hasattr(block, "type") and block.type == "text":
                    texts.append(getattr(block, "text", "") or "")
            return "".join(texts)
        return ""

    def _save_acp_event_to_db(
        event_type: str, event_data: dict[str, Any], db_session: Session
    ) -> None:
        """Save an ACP event as a separate message in the database."""
        # Save tool calls, thinking, and plan updates as separate messages
        if event_type in [
            "tool_call_start",
            "tool_call_progress",
            "agent_thought_chunk",
            "agent_plan_update",
        ]:
            create_message(
                session_id=session_id,
                message_type=MessageType.ASSISTANT,
                content="",  # Empty content for structured events
                db_session=db_session,
                message_metadata=event_data,
            )

    try:
        logger.warning(f"[STREAM] Starting stream for session {session_id}")
        with get_session_with_current_tenant() as db_session:
            # Verify session exists and belongs to user
            logger.warning(f"[STREAM] Verifying session {session_id} exists")
            session = get_build_session(session_id, user_id, db_session)
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
            update_session_activity(session_id, db_session)

            # Save user message to database
            logger.warning(
                f"[STREAM] Saving user message to DB for session {session_id}"
            )
            user_message = create_message(
                session_id=session_id,
                message_type=MessageType.USER,
                content=user_message_content,
                db_session=db_session,
            )
            logger.warning(f"[STREAM] User message {user_message.id} saved")

            # Get sandbox
            sandbox = get_sandbox_by_session_id(db_session, session_id)
            if sandbox is None:
                logger.warning(f"[STREAM] Sandbox not found for session {session_id}")
                yield _format_packet_event(ErrorPacket(message="Sandbox not found"))
                return

            sandbox_id = str(sandbox.id)
            logger.warning(
                f"[STREAM] Found sandbox {sandbox_id} for session {session_id}"
            )

            sandbox_manager = SandboxManager()
            logger.warning(
                f"[STREAM] Starting to stream ACP events from sandbox {sandbox_id}"
            )

            # Stream ACP events directly to frontend
            event_count = 0
            for acp_event in sandbox_manager.send_message(
                sandbox_id, user_message_content, db_session
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
                    # Accumulate text for DB storage
                    text = _extract_text_from_content(acp_event.content)
                    if text:
                        assistant_message_parts.append(text)
                    yield _serialize_acp_event(acp_event, "agent_message_chunk")

                elif isinstance(acp_event, AgentThoughtChunk):
                    # Save thinking step to DB
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "agent_thought_chunk"
                    _save_acp_event_to_db("agent_thought_chunk", event_data, db_session)
                    yield _serialize_acp_event(acp_event, "agent_thought_chunk")

                elif isinstance(acp_event, ToolCallStart):
                    logger.warning(
                        f"[STREAM] Tool started: {acp_event.kind} - {acp_event.title}"
                    )
                    # Save tool call start to DB
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "tool_call_start"
                    _save_acp_event_to_db("tool_call_start", event_data, db_session)
                    yield _serialize_acp_event(acp_event, "tool_call_start")

                elif isinstance(acp_event, ToolCallProgress):
                    logger.warning(
                        f"[STREAM] Tool progress: {acp_event.kind} - {acp_event.status}"
                    )
                    # Save tool call progress to DB
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "tool_call_progress"
                    _save_acp_event_to_db("tool_call_progress", event_data, db_session)
                    yield _serialize_acp_event(acp_event, "tool_call_progress")

                    # Emit file_write packet for write/edit operations (custom packet)
                    if acp_event.kind and acp_event.kind.lower() in [
                        "write",
                        "write_file",
                        "edit",
                    ]:
                        # Try to get file path from the tool result
                        file_path = "outputs/file"  # Default path
                        if hasattr(acp_event, "content") and acp_event.content:
                            # Try to extract path from content
                            for item in (
                                acp_event.content
                                if isinstance(acp_event.content, list)
                                else [acp_event.content]
                            ):
                                if hasattr(item, "text") and item.text:
                                    # Look for path in the text
                                    if "/" in item.text or "\\" in item.text:
                                        file_path = item.text.split("\n")[0][:200]
                                        break
                        file_write_packet = FileWritePacket(
                            path=file_path,
                            size_bytes=0,  # Size not always available
                        )
                        logger.warning(f"[STREAM] File write detected: {file_path}")
                        yield _format_packet_event(file_write_packet)

                elif isinstance(acp_event, AgentPlanUpdate):
                    logger.warning("[STREAM] Plan update received")
                    # Save plan update to DB
                    event_data = acp_event.model_dump(
                        mode="json", by_alias=True, exclude_none=False
                    )
                    event_data["type"] = "agent_plan_update"
                    _save_acp_event_to_db("agent_plan_update", event_data, db_session)
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
            # For now, only check for web apps
            logger.warning(f"[STREAM] Checking for artifacts in sandbox {sandbox_id}")
            sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox_id)
            outputs_dir = sandbox_path / "outputs"

            if outputs_dir.exists():
                logger.warning(f"[STREAM] Outputs directory exists: {outputs_dir}")
                # Check for webapp
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

            # Save the complete assistant response to database (same session!)
            if assistant_message_parts:
                total_chars = len("".join(assistant_message_parts))
                logger.warning(
                    f"[STREAM] Saving assistant response ({total_chars} chars) to DB"
                )
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    content="".join(assistant_message_parts),
                    db_session=db_session,
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
        logger.warning(f"[STREAM] Stream generator finished for session {session_id}")
        logger.debug(f"Stream generator finished for session {session_id}")


@router.post("/sessions/{session_id}/send-message", tags=PUBLIC_API_TAGS)
async def send_message(
    session_id: UUID,
    request: MessageRequest,
    user: User | None = Depends(current_user),
    _rate_limit_check: None = Depends(check_build_rate_limits),
):
    """
    Send a message to the CLI agent and stream the response.

    Enforces rate limiting before executing the agent (via dependency).
    Returns a Server-Sent Events (SSE) stream with the agent's response.

    Follows the same pattern as /chat/send-message for consistency.
    """
    user_id = user.id if user is not None else None

    # Stream the CLI agent's response
    # All database operations (validation, message creation, etc.) happen inside the generator
    return StreamingResponse(
        stream_cli_agent_response(session_id, request.content, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
