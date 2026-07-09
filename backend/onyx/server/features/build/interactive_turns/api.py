"""Attach-only API endpoints for active interactive Craft turns."""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.interactive_turns.executor import (
    start_interactive_turn_runner,
)
from onyx.server.features.build.interactive_turns.models import InteractiveTurnResponse
from onyx.server.features.build.interactive_turns.state import get_active_turn
from onyx.server.features.build.interactive_turns.state import get_turn
from onyx.server.features.build.interactive_turns.state import TURN_STATUS_FAILED
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.streaming import SSE_KEEPALIVE
from onyx.utils.logger import setup_logger

router = APIRouter()
logger = setup_logger()

LIVE_STREAM_READY_POLL_SECONDS = 0.25
LIVE_STREAM_KEEPALIVE_SECONDS = 15.0
LIVE_STREAM_RUNNER_RETRY_SECONDS = 5.0
TERMINAL_STREAM_EVENT_TYPES = frozenset(("prompt_response", "error"))


def _format_stream_error(detail: str) -> str:
    payload = {
        "type": "error",
        "message": detail,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _stream_chunk_type(chunk: str) -> str | None:
    for line in chunk.splitlines():
        if not line.startswith("data:"):
            continue
        raw_data = line[line.index(":") + 1 :].strip()
        if not raw_data:
            continue
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            return None
        event_type = payload.get("type")
        return event_type if isinstance(event_type, str) else None
    return None


def _turn_state_for_stream(
    *,
    cache: CacheBackend,
    turn_id: UUID,
    session_id: UUID,
    user_id: UUID,
) -> tuple[bool, str | None]:
    turn = get_active_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
    )
    if turn is not None and turn.turn_id == turn_id:
        return True, None
    turn = get_turn(cache, turn_id)
    if turn is None or turn.session_id != session_id or turn.user_id != user_id:
        return False, None
    if turn.status != TURN_STATUS_FAILED:
        return False, None
    return False, turn.error_detail or "Interactive turn failed."


def _try_start_turn_runner(turn_id: UUID) -> None:
    try:
        start_interactive_turn_runner(turn_id)
    except Exception:
        logger.exception(
            "Failed to start interactive turn runner for turn %s; will retry on attach",
            turn_id,
        )


@router.get("/sessions/{session_id}/turns/active", tags=PUBLIC_API_TAGS)
def get_active_interactive_turn(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> InteractiveTurnResponse | None:
    """Return the active interactive turn for a Craft session, if any."""
    session = get_build_session(session_id, user.id, db_session)
    if session is None:
        raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

    cache = get_cache_backend()
    turn = get_active_turn(
        cache=cache,
        session_id=session_id,
        user_id=user.id,
    )
    return InteractiveTurnResponse.from_turn(turn) if turn else None


@router.get("/sessions/{session_id}/turns/{turn_id}/events", tags=PUBLIC_API_TAGS)
def get_interactive_turn_events(
    session_id: UUID,
    turn_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """Attach to live opencode events for an active interactive turn."""
    session = get_build_session(session_id, user.id, db_session)
    if session is None:
        raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

    cache = get_cache_backend()
    turn = get_active_turn(
        cache=cache,
        session_id=session_id,
        user_id=user.id,
    )
    initial_error_detail: str | None = None
    if turn is None or turn.turn_id != turn_id:
        requested_turn = get_turn(cache, turn_id)
        if (
            requested_turn is None
            or requested_turn.session_id != session_id
            or requested_turn.user_id != user.id
            or requested_turn.status != TURN_STATUS_FAILED
        ):
            raise OnyxError(OnyxErrorCode.CONFLICT, "Interactive turn is not running")
        initial_error_detail = requested_turn.error_detail or "Interactive turn failed."

    user_id = user.id

    def stream_generator() -> Generator[str, None, None]:
        if initial_error_detail is not None:
            yield _format_stream_error(initial_error_detail)
            return

        last_runner_start_attempt = 0.0

        def maybe_start_runner(*, force: bool = False) -> None:
            nonlocal last_runner_start_attempt
            now = time.monotonic()
            if (
                not force
                and now - last_runner_start_attempt < LIVE_STREAM_RUNNER_RETRY_SECONDS
            ):
                return
            last_runner_start_attempt = now
            _try_start_turn_runner(turn_id)

        maybe_start_runner(force=True)
        while True:
            active, error_detail = _turn_state_for_stream(
                cache=cache,
                turn_id=turn_id,
                session_id=session_id,
                user_id=user_id,
            )
            if not active:
                if error_detail:
                    yield _format_stream_error(error_detail)
                return

            with get_session_with_current_tenant() as stream_db_session:
                session = get_build_session(session_id, user_id, stream_db_session)
                if session is None:
                    yield _format_stream_error("Session not found")
                    return
                if session.opencode_session_id:
                    break

            yield SSE_KEEPALIVE
            maybe_start_runner()
            time.sleep(LIVE_STREAM_READY_POLL_SECONDS)

        try:
            with get_session_with_current_tenant() as stream_db_session:
                session_manager = SessionManager(stream_db_session)
                terminal_error_detail: str | None = None
                for chunk in session_manager.subscribe_to_existing_session_events(
                    session_id,
                    user_id,
                    keepalive_seconds=LIVE_STREAM_KEEPALIVE_SECONDS,
                ):
                    yield chunk
                    chunk_type = _stream_chunk_type(chunk)
                    if chunk_type in TERMINAL_STREAM_EVENT_TYPES:
                        return

                    stream_db_session.expire_all()
                    active, error_detail = _turn_state_for_stream(
                        cache=cache,
                        turn_id=turn_id,
                        session_id=session_id,
                        user_id=user_id,
                    )
                    if not active:
                        terminal_error_detail = error_detail or terminal_error_detail
                        if chunk_type is None:
                            if terminal_error_detail:
                                yield _format_stream_error(terminal_error_detail)
                            return
                        # Keep draining already-queued live events until the
                        # terminal packet arrives or a keepalive proves the
                        # subscriber queue has gone idle.
                        continue
                    terminal_error_detail = None
                if terminal_error_detail:
                    yield _format_stream_error(terminal_error_detail)
        except GeneratorExit:
            logger.info(
                "Interactive turn live stream disconnected for session %s turn %s",
                session_id,
                turn_id,
            )
            raise
        except OnyxError as exc:
            yield _format_stream_error(exc.detail)
        except Exception as exc:
            logger.exception(
                "Interactive turn live stream failed for session %s turn %s",
                session_id,
                turn_id,
            )
            yield _format_stream_error(str(exc))

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
