"""API endpoints for Build Mode message management."""

from uuid import UUID

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
from onyx.server.features.build.models import MessageListResponse
from onyx.server.features.build.models import MessageRequest
from onyx.server.features.build.models import MessageResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


router = APIRouter(prefix="/build/sessions/{session_id}/messages")


@router.get("/", tags=PUBLIC_API_TAGS)
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
):
    """
    Stream the CLI agent's response using SSE format.

    The assistant's response is accumulated during streaming and saved to the
    database only AFTER the full response is generated. If the user refreshes
    or disconnects during response generation, that partial response is lost.

    This is a stub implementation. The actual CLI agent communication
    will be implemented when the CLI agent integration is ready.

    NOTE: Packet types (as defined in plan):
    - step_start: Begin a logical step (e.g., "Reading requirements")
    - step_delta: Progress within a step
    - tool_start: Agent invoking a tool (bash, read, write, etc.)
    - file_write: File written to sandbox
    - artifact_created: New artifact generated
    - output_start: Begin agent's text output
    - output_delta: Incremental agent text output (accumulated for DB)
    - done: Signal completion with summary

    Only output_delta content is accumulated and saved to database as MESSAGE.
    All packets include timestamps.
    """
    from datetime import datetime

    # Accumulate the full assistant response (only output_delta packets)
    full_response = []

    # Get current timestamp
    def get_timestamp():
        return datetime.utcnow().isoformat() + "Z"

    # Example step_start packet - agent begins analyzing
    yield (
        f'event: message\ndata: {{"type": "step_start", "step_id": "analyze_001", '
        f'"title": "Analyzing your request", "timestamp": "{get_timestamp()}"}}\n\n'
    )

    # Example step_delta packet - progress update within step
    yield (
        f'event: message\ndata: {{"type": "step_delta", "step_id": "analyze_001", '
        f'"content": "Examining the requirements and context...", '
        f'"timestamp": "{get_timestamp()}"}}\n\n'
    )

    # Example tool_start packet - agent calling a tool
    yield (
        f'event: message\ndata: {{"type": "tool_start", "tool_name": "bash", '
        f'"tool_input": {{"command": "ls -la /workspace"}}, '
        f'"timestamp": "{get_timestamp()}"}}\n\n'
    )

    # Example file_write packet - file written to sandbox
    yield (
        f'event: message\ndata: {{"type": "file_write", '
        f'"path": "outputs/web/src/App.tsx", "size_bytes": 1523, '
        f'"timestamp": "{get_timestamp()}"}}\n\n'
    )

    # Example artifact_created packet
    yield (
        f'event: message\ndata: {{"type": "artifact_created", '
        f'"artifact": {{"id": "uuid-placeholder", "type": "web_app", '
        f'"name": "Dashboard", "path": "outputs/web/"}}, '
        f'"timestamp": "{get_timestamp()}"}}\n\n'
    )

    # Example output_start packet - agent begins text output
    yield f'event: message\ndata: {{"type": "output_start", "timestamp": "{get_timestamp()}"}}\n\n'

    # Example output_delta packets - agent's response text (this gets saved to DB)
    response_part1 = "I've analyzed your request and created a dashboard application. "
    full_response.append(response_part1)
    yield f'event: message\ndata: {{"type": "output_delta", "content": "{response_part1}", "timestamp": "{get_timestamp()}"}}\n\n'

    response_part2 = "The application includes the following features: data visualization, filtering, and export capabilities."
    full_response.append(response_part2)
    yield f'event: message\ndata: {{"type": "output_delta", "content": "{response_part2}", "timestamp": "{get_timestamp()}"}}\n\n'

    # Signal completion with summary
    yield (
        f'event: message\ndata: {{"type": "done", '
        f'"summary": "Created a Next.js dashboard with 3 components", '
        f'"timestamp": "{get_timestamp()}"}}\n\n'
    )

    # Save the complete assistant response to database
    # Only output_delta packets are accumulated and saved as the message
    # We create a new session here because the request-scoped session is closed
    tenant_id = get_current_tenant_id()
    with get_session_with_current_tenant(tenant_id) as new_db_session:
        create_message(
            session_id=session_id,
            message_type=MessageType.ASSISTANT,
            content="".join(full_response),
            db_session=new_db_session,
        )
        logger.info(f"Saved assistant response for session {session_id}")


@router.post("/", tags=PUBLIC_API_TAGS)
async def send_message(
    session_id: UUID,
    request: MessageRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
):
    """
    Send a message to the CLI agent and stream the response.

    Returns a Server-Sent Events (SSE) stream with the agent's response.
    """
    user_id = user.id if user is not None else None

    # Verify session exists and belongs to user
    session = get_build_session(session_id, user_id, db_session)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check if sandbox is running
    if not session.sandbox or session.sandbox.status != SandboxStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail="Sandbox is not running. Please wait for it to start.",
        )

    # Update last activity timestamp
    update_session_activity(session_id, db_session)

    # Save user message to database
    user_message = create_message(
        session_id=session_id,
        message_type=MessageType.USER,
        content=request.content,
        db_session=db_session,
    )

    logger.info(f"User message {user_message.id} sent to session {session_id}")

    # Stream the CLI agent's response
    # The assistant's response will be saved to the database after streaming completes
    return StreamingResponse(
        stream_cli_agent_response(session_id, request.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
