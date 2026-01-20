"""API endpoints for Build Mode message management."""

import json
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
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
from onyx.db.build_session import create_message
from onyx.db.build_session import get_build_session
from onyx.db.build_session import get_session_messages
from onyx.db.build_session import update_session_activity
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.server.features.build.models import MessageListResponse
from onyx.server.features.build.models import MessageRequest
from onyx.server.features.build.models import MessageResponse
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
    from onyx.server.features.build.rate_limit import get_user_rate_limit_status

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
    - output_start: Begin agent's text output
    - output_delta: Incremental agent text output (from AgentMessageChunk, accumulated for DB)
    - done: Signal completion with summary (from PromptResponse)
    - error: An error occurred (from Error)
    """
    # Accumulate assistant message content (from output_delta packets)
    assistant_message_parts: list[str] = []
    output_started = False

    def _format_message_event(data: dict) -> str:
        """Format a message event as SSE (all events use event: message)."""
        return f"event: message\ndata: {json.dumps(data)}\n\n"

    def _get_timestamp() -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(tz=timezone.utc).isoformat()

    try:
        # Create ONE session for the entire streaming operation (following chat pattern)
        with get_session_with_current_tenant() as db_session:
            # Verify session exists and belongs to user
            session = get_build_session(session_id, user_id, db_session)
            if session is None:
                yield _format_message_event(
                    {
                        "type": "error",
                        "message": "Session not found",
                        "timestamp": _get_timestamp(),
                    }
                )
                return

            # Check if sandbox is running
            if not session.sandbox or session.sandbox.status != SandboxStatus.RUNNING:
                yield _format_message_event(
                    {
                        "type": "error",
                        "message": "Sandbox is not running. Please wait for it to start.",
                        "timestamp": _get_timestamp(),
                    }
                )
                return

            # Update last activity timestamp
            update_session_activity(session_id, db_session)

            # Save user message to database
            user_message = create_message(
                session_id=session_id,
                message_type=MessageType.USER,
                content=user_message_content,
                db_session=db_session,
            )
            logger.info(f"User message {user_message.id} sent to session {session_id}")

            # Get sandbox
            sandbox = get_sandbox_by_session_id(db_session, session_id)
            if sandbox is None:
                yield _format_message_event(
                    {
                        "type": "error",
                        "message": "Sandbox not found",
                        "timestamp": _get_timestamp(),
                    }
                )
                return

            sandbox_id = str(sandbox.id)
            sandbox_session_id = sandbox.session_id

            sandbox_manager = SandboxManager()

            # Stream ACP events from agent and map to frontend format
            for acp_event in sandbox_manager.send_message(
                sandbox_id, user_message_content, db_session
            ):
                # Map ACP events to frontend packet types
                if isinstance(acp_event, AgentThoughtChunk):
                    # Map thought to step_delta
                    # AgentThoughtChunk has a content field which is a ContentBlock (TextContentBlock, etc.)
                    content_block = getattr(acp_event, "content", None)
                    if content_block and hasattr(content_block, "text"):
                        text = content_block.text
                        yield _format_message_event(
                            {
                                "type": "step_delta",
                                "step_id": "thinking",
                                "content": text,
                                "timestamp": _get_timestamp(),
                            }
                        )

                elif isinstance(acp_event, ToolCallStart):
                    # Emit tool_start packet
                    tool_name = getattr(acp_event, "tool_name", "unknown")
                    tool_input = getattr(acp_event, "input", {})
                    yield _format_message_event(
                        {
                            "type": "tool_start",
                            "tool_name": tool_name,
                            "tool_input": tool_input,
                            "timestamp": _get_timestamp(),
                        }
                    )

                elif isinstance(acp_event, ToolCallProgress):
                    # Emit tool_end packet
                    tool_name = getattr(acp_event, "tool_name", "")
                    yield _format_message_event(
                        {
                            "type": "tool_end",
                            "tool_name": tool_name,
                            "status": "success",
                            "timestamp": _get_timestamp(),
                        }
                    )

                    # If it's a write operation, emit file_write packet
                    if tool_name.lower() in ["write", "write_file", "edit"]:
                        result = getattr(acp_event, "result", "")
                        yield _format_message_event(
                            {
                                "type": "file_write",
                                "path": "outputs/file",
                                "size_bytes": len(str(result)),
                                "timestamp": _get_timestamp(),
                            }
                        )

                elif isinstance(acp_event, AgentPlanUpdate):
                    # Emit plan update
                    plan = getattr(acp_event, "plan", "")
                    if plan:
                        yield _format_message_event(
                            {
                                "type": "plan",
                                "plan": plan,
                                "timestamp": _get_timestamp(),
                            }
                        )

                elif isinstance(acp_event, CurrentModeUpdate):
                    # Emit mode change update
                    mode = getattr(acp_event, "mode", "")
                    if mode:
                        yield _format_message_event(
                            {
                                "type": "mode_update",
                                "mode": mode,
                                "timestamp": _get_timestamp(),
                            }
                        )

                elif isinstance(acp_event, AgentMessageChunk):
                    # Start output if not started
                    if not output_started:
                        yield _format_message_event(
                            {
                                "type": "output_start",
                                "timestamp": _get_timestamp(),
                            }
                        )
                        output_started = True

                    # Emit output_delta and accumulate content
                    # AgentMessageChunk has a content field which is a ContentBlock (TextContentBlock, etc.)
                    content_block = getattr(acp_event, "content", None)
                    if content_block and hasattr(content_block, "text"):
                        text = content_block.text
                        assistant_message_parts.append(text)
                        yield _format_message_event(
                            {
                                "type": "output_delta",
                                "content": text,
                                "timestamp": _get_timestamp(),
                            }
                        )

                elif isinstance(acp_event, PromptResponse):
                    # Agent finished - emit done packet
                    stop_reason = getattr(acp_event, "stop_reason", None)
                    summary = (
                        f"Completed: {stop_reason}" if stop_reason else "Task completed"
                    )
                    yield _format_message_event(
                        {
                            "type": "done",
                            "summary": summary,
                            "timestamp": _get_timestamp(),
                        }
                    )

                elif isinstance(acp_event, ACPError):
                    # Emit error packet
                    yield _format_message_event(
                        {
                            "type": "error",
                            "message": acp_event.message,
                            "timestamp": _get_timestamp(),
                        }
                    )

            # Check for artifacts and emit artifact_created events
            sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox_session_id)
            outputs_dir = sandbox_path / "outputs"

            if outputs_dir.exists():
                # Check for webapp
                web_dir = outputs_dir / "web"
                if web_dir.exists():
                    yield _format_message_event(
                        {
                            "type": "artifact_created",
                            "artifact": {
                                "id": str(uuid.uuid4()),
                                "type": "web_app",
                                "name": "Web Application",
                                "path": "outputs/web/",
                                "preview_url": (
                                    f"/api/build/sessions/{session_id}/" "preview"
                                ),
                            },
                            "timestamp": _get_timestamp(),
                        }
                    )

                # Check for markdown files
                for md_file in outputs_dir.glob("**/*.md"):
                    yield _format_message_event(
                        {
                            "type": "artifact_created",
                            "artifact": {
                                "id": str(uuid.uuid4()),
                                "type": "markdown",
                                "name": md_file.stem,
                                "path": str(md_file.relative_to(sandbox_path)),
                                "preview_url": None,
                            },
                            "timestamp": _get_timestamp(),
                        }
                    )

                # Check for images
                for img_ext in ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg"]:
                    for img_file in outputs_dir.glob(f"**/{img_ext}"):
                        yield _format_message_event(
                            {
                                "type": "artifact_created",
                                "artifact": {
                                    "id": str(uuid.uuid4()),
                                    "type": "image",
                                    "name": img_file.name,
                                    "path": str(img_file.relative_to(sandbox_path)),
                                    "preview_url": (
                                        f"/api/build/sessions/{session_id}/"
                                        f"artifacts/{img_file.relative_to(sandbox_path)}"
                                    ),
                                },
                                "timestamp": _get_timestamp(),
                            }
                        )

                # Check for PowerPoint files
                for pptx_file in outputs_dir.glob("**/*.pptx"):
                    yield _format_message_event(
                        {
                            "type": "artifact_created",
                            "artifact": {
                                "id": str(uuid.uuid4()),
                                "type": "pptx",
                                "name": pptx_file.stem,
                                "path": str(pptx_file.relative_to(sandbox_path)),
                                "preview_url": (
                                    f"/api/build/sessions/{session_id}/"
                                    f"artifacts/{pptx_file.relative_to(sandbox_path)}"
                                ),
                            },
                            "timestamp": _get_timestamp(),
                        }
                    )

                # Check for Excel files
                for xlsx_file in outputs_dir.glob("**/*.xlsx"):
                    yield _format_message_event(
                        {
                            "type": "artifact_created",
                            "artifact": {
                                "id": str(uuid.uuid4()),
                                "type": "csv",
                                "name": xlsx_file.stem,
                                "path": str(xlsx_file.relative_to(sandbox_path)),
                                "preview_url": (
                                    f"/api/build/sessions/{session_id}/"
                                    f"artifacts/{xlsx_file.relative_to(sandbox_path)}"
                                ),
                            },
                            "timestamp": _get_timestamp(),
                        }
                    )

                # Check for Word documents
                for docx_file in outputs_dir.glob("**/*.docx"):
                    yield _format_message_event(
                        {
                            "type": "artifact_created",
                            "artifact": {
                                "id": str(uuid.uuid4()),
                                "type": "markdown",
                                "name": docx_file.stem,
                                "path": str(docx_file.relative_to(sandbox_path)),
                                "preview_url": (
                                    f"/api/build/sessions/{session_id}/"
                                    f"artifacts/{docx_file.relative_to(sandbox_path)}"
                                ),
                            },
                            "timestamp": _get_timestamp(),
                        }
                    )

            # Save the complete assistant response to database (same session!)
            if assistant_message_parts:
                create_message(
                    session_id=session_id,
                    message_type=MessageType.ASSISTANT,
                    content="".join(assistant_message_parts),
                    db_session=db_session,
                )
                logger.info(f"Saved assistant response for session {session_id}")

    except ValueError as e:
        logger.error(f"Error executing task: {e}")
        yield _format_message_event(
            {
                "type": "error",
                "message": str(e),
                "timestamp": _get_timestamp(),
            }
        )
    except RuntimeError as e:
        logger.error(f"Agent communication error: {e}")
        yield _format_message_event(
            {
                "type": "error",
                "message": str(e),
                "timestamp": _get_timestamp(),
            }
        )
    except Exception as e:
        logger.exception("Error in build message streaming")
        yield _format_message_event(
            {
                "type": "error",
                "message": str(e),
                "timestamp": _get_timestamp(),
            }
        )
    finally:
        logger.debug(f"Stream generator finished for session {session_id}")


@router.post("/sessions/{session_id}/messages", tags=PUBLIC_API_TAGS)
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
