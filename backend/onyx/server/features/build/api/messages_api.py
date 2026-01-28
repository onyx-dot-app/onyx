"""API endpoints for Build Mode message management."""

from collections.abc import Generator
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.server.features.build.api.models import MessageListResponse
from onyx.server.features.build.api.models import MessageRequest
from onyx.server.features.build.api.models import MessageResponse
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.session.manager import RateLimitError
from onyx.server.features.build.session.manager import SessionManager
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter()


def check_build_rate_limits(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    """
    Dependency to check build mode rate limits before processing the request.

    Raises HTTPException(429) if rate limit is exceeded.
    Follows the same pattern as chat's check_token_rate_limits.
    """
    session_manager = SessionManager(db_session)

    try:
        session_manager.check_rate_limit(user)
    except RateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail=str(e),
        )


@router.get("/sessions/{session_id}/messages", tags=PUBLIC_API_TAGS)
def list_messages(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> MessageListResponse:
    """Get all messages for a build session."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = SessionManager(db_session)

    messages = session_manager.list_messages(session_id, user.id)

    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return MessageListResponse(
        messages=[MessageResponse.from_model(msg) for msg in messages]
    )


@router.post("/sessions/{session_id}/send-message", tags=PUBLIC_API_TAGS)
def send_message(
    session_id: UUID,
    request: MessageRequest,
    user: User = Depends(current_user),
    _rate_limit_check: None = Depends(check_build_rate_limits),
) -> StreamingResponse:
    """
    Send a message to the CLI agent and stream the response.

    Enforces rate limiting before executing the agent (via dependency).
    Returns a Server-Sent Events (SSE) stream with the agent's response.

    Follows the same pattern as /chat/send-message for consistency.
    """

    def stream_generator() -> Generator[str, None, None]:
        """Stream generator that manages its own database session.

        This is necessary because StreamingResponse consumes the generator
        AFTER the endpoint returns, at which point FastAPI's dependency-injected
        db_session has already been closed. By creating a new session inside
        the generator, we ensure the session remains open for the entire
        streaming duration.
        """
        # Capture user info needed for streaming (user object may not be available
        # after the endpoint returns due to dependency cleanup)
        user_id = user.id
        message_content = request.content

        with get_session_with_current_tenant() as db_session:
            # Update sandbox heartbeat - this is the only place we track activity
            # for determining when a sandbox should be put to sleep
            sandbox = get_sandbox_by_user_id(db_session, user.id)
            if sandbox and sandbox.status.is_active():
                update_sandbox_heartbeat(db_session, sandbox.id)

            session_manager = SessionManager(db_session)
            yield from session_manager.send_message(
                session_id, user_id, message_content
            )

    # Stream the CLI agent's response
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
