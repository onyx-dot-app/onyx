"""API endpoints for Build Mode message management."""

from collections.abc import Generator
from uuid import UUID
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import MessageType
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.build_session import count_user_messages
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.interactive_turns.executor import (
    start_interactive_turn_runner,
)
from onyx.server.features.build.interactive_turns.models import InteractiveTurnResponse
from onyx.server.features.build.interactive_turns.state import acquire_active_turn_lock
from onyx.server.features.build.interactive_turns.state import create_interactive_turn
from onyx.server.features.build.interactive_turns.state import finish_turn
from onyx.server.features.build.interactive_turns.state import get_active_turn
from onyx.server.features.build.interactive_turns.state import get_turn_for_request
from onyx.server.features.build.interactive_turns.state import InteractiveTurnLockError
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_FAILED
from onyx.server.features.build.session.errors import RateLimitError
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.models import MessageInterruptResponse
from onyx.server.features.build.session.models import MessageListResponse
from onyx.server.features.build.session.models import MessageRequest
from onyx.server.features.build.session.models import MessageResponse
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter()


def check_build_rate_limits(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MessageListResponse:
    """Get all messages for a build session."""
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> InteractiveTurnResponse:
    """Start an interactive Craft turn in the background."""
    session = get_build_session(session_id, user.id, db_session)
    if session is None:
        raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

    cache = get_cache_backend()
    client_request_id = request.client_request_id or str(uuid4())

    try:
        lock = acquire_active_turn_lock(cache, session_id)
    except InteractiveTurnLockError as exc:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This session is busy with a previous turn.",
        ) from exc

    lock_released = False
    try:
        existing = get_turn_for_request(
            cache=cache,
            session_id=session_id,
            user_id=user.id,
            client_request_id=client_request_id,
        )
        if existing is not None:
            return InteractiveTurnResponse.from_turn(existing)

        active = get_active_turn(cache=cache, session_id=session_id, user_id=user.id)
        if active is not None:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "This session is busy with a previous turn.",
            )

        check_build_rate_limits(user=user, db_session=db_session)
        # Craft turns also respect the org/user token + cost budgets. No-op when
        # none are configured; raises the structured 429 when over budget.
        check_token_rate_limits(user)

        turn_index = count_user_messages(session_id, db_session)
        if request.provider and request.model:
            session.agent_provider = request.provider
            session.agent_model = request.model
        create_message(
            session_id=session_id,
            message_type=MessageType.USER,
            turn_index=turn_index,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": request.content},
            },
            db_session=db_session,
        )

        turn = create_interactive_turn(
            cache=cache,
            session_id=session_id,
            user_id=user.id,
            client_request_id=client_request_id,
            prompt=request.content,
            turn_index=turn_index,
        )

        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
            lock.release()
            lock_released = True
            finish_turn(
                cache=cache,
                turn_id=turn.turn_id,
                status=TURN_STATUS_FAILED,
                error_detail="Failed to persist user message.",
            )
            raise
    finally:
        if not lock_released:
            lock.release()

    try:
        start_interactive_turn_runner(turn.turn_id)
    except Exception:
        logger.exception(
            "Failed to start interactive turn %s; attach endpoints will retry",
            turn.turn_id,
        )

    return InteractiveTurnResponse.from_turn(turn)


@router.post(
    "/sessions/{session_id}/subagents/{subagent_session_id}/send-message",
    tags=PUBLIC_API_TAGS,
)
def send_subagent_message(
    session_id: UUID,
    subagent_session_id: str,
    request: MessageRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    _rate_limit_check: None = Depends(check_build_rate_limits),
    # Craft turns also respect the org/user token + cost budgets (no-op when none).
    _token_rate_limit_check: None = Depends(check_token_rate_limits),
) -> StreamingResponse:
    """
    Send a follow-up message to a subagent's child opencode session and
    stream the response.

    The subagent session must be a child opencode session spawned under this
    build session; a bogus id surfaces as an upstream error event in the SSE
    stream. Returns a Server-Sent Events (SSE) stream, mirroring
    /sessions/{session_id}/send-message.
    """

    def stream_generator() -> Generator[str, None, None]:
        # Capture values needed for streaming before the endpoint returns and
        # FastAPI tears down the dependency-injected db_session.
        user_id = user.id
        message_content = request.content
        events_yielded = 0

        try:
            with get_session_with_current_tenant() as db_session:
                sandbox = get_sandbox_by_user_id(db_session, user.id)
                if sandbox and sandbox.status.is_active():
                    update_sandbox_heartbeat(db_session, sandbox.id)

                session_manager = SessionManager(db_session)
                for chunk in session_manager.send_subagent_message(
                    session_id,
                    user_id,
                    subagent_session_id,
                    message_content,
                ):
                    events_yielded += 1
                    yield chunk
        except GeneratorExit:
            logger.warning(
                "Subagent stream disconnected for session %s subagent %s after "
                "%d events (client likely closed connection)",
                session_id,
                subagent_session_id,
                events_yielded,
            )
        except Exception:
            logger.exception(
                "Subagent stream error for session %s subagent %s after %d events",
                session_id,
                subagent_session_id,
                events_yielded,
            )

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/sessions/{session_id}/interrupt", tags=PUBLIC_API_TAGS)
def interrupt_message(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MessageInterruptResponse:
    """Interrupt the in-flight agent turn for a session.

    Interrupts the opencode-serve turn inside the sandbox; attached turn-event
    streams then terminate through their normal completion path.
    """
    session_manager = SessionManager(db_session)
    interrupted = session_manager.interrupt_message(session_id, user.id)
    return MessageInterruptResponse(interrupted=interrupted)
