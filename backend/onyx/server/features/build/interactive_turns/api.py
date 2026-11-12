"""Attach-only API endpoints for active interactive Craft turns."""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from contextlib import closing
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.interactive_turns.executor import (
    start_interactive_turn_runner,
)
from onyx.server.features.build.interactive_turns.models import (
    InteractiveTurnCompletedPacket,
    InteractiveTurnResponse,
)
from onyx.server.features.build.interactive_turns.state import (
    InteractiveTurn,
    get_active_turn,
    get_turn,
)
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.streaming import SSE_KEEPALIVE
from onyx.server.features.build.timeouts import POLL_INTERVAL_SECONDS
from onyx.utils.logger import setup_logger

router = APIRouter()
logger = setup_logger()

TERMINAL_STREAM_EVENT_TYPES = frozenset(("prompt_response", "error"))

# Throttle on runner-claim retries from the attach stream; must be well under
# RUNNER_STALE_AFTER_SECONDS so a stolen turn restarts promptly.
LIVE_STREAM_RUNNER_RETRY_SECONDS = 5.0

# Catch completion when the agent ends just before the live subscription opens.
LIVE_STREAM_KEEPALIVE_SECONDS = 1.0

# Cache-only handoff after the agent stops; expiry falls back to stream reconnect.
TURN_COMPLETION_CHECK_SECONDS = 0.2
TURN_COMPLETION_WAIT_SECONDS = 30.0


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


def _owned_turn(
    *, cache: CacheBackend, turn_id: UUID, session_id: UUID, user_id: UUID
) -> InteractiveTurn | None:
    turn = get_turn(cache, turn_id)
    if turn is None or turn.session_id != session_id or turn.user_id != user_id:
        return None
    return turn


def _format_turn_completed(turn: InteractiveTurn) -> str:
    packet = InteractiveTurnCompletedPacket.from_turn(turn)
    return f"event: message\ndata: {packet.model_dump_json()}\n\n"


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


@router.get("/sessions/{session_id}/turns/{turn_id}", tags=PUBLIC_API_TAGS)
def get_interactive_turn(
    session_id: UUID,
    turn_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> InteractiveTurnResponse | None:
    """Return a known turn's outcome, including terminal states."""
    if get_build_session(session_id, user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")
    turn = _owned_turn(
        cache=get_cache_backend(),
        turn_id=turn_id,
        session_id=session_id,
        user_id=user.id,
    )
    return InteractiveTurnResponse.from_turn(turn) if turn else None


@router.get("/sessions/{session_id}/turns/{turn_id}/events", tags=PUBLIC_API_TAGS)
def get_interactive_turn_events(
    session_id: UUID,
    turn_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> StreamingResponse:
    """Stream an owned turn through finalization, or replay its terminal outcome."""
    user_id = user.id
    with get_session_with_current_tenant() as db_session:
        if get_build_session(session_id, user_id, db_session) is None:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Session not found")

    cache = get_cache_backend()
    requested_turn = _owned_turn(
        cache=cache, turn_id=turn_id, session_id=session_id, user_id=user_id
    )
    if requested_turn is None:
        raise OnyxError(OnyxErrorCode.CONFLICT, "Interactive turn is unavailable")

    def stream_generator() -> Generator[str, None, None]:
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
            try:
                start_interactive_turn_runner(turn_id)
            except Exception:
                logger.exception(
                    "Failed to start interactive turn runner for turn %s; will retry on attach",
                    turn_id,
                )

        def current_turn() -> InteractiveTurn | None:
            return _owned_turn(
                cache=cache, turn_id=turn_id, session_id=session_id, user_id=user_id
            )

        try:
            turn = current_turn()
            if turn is None:
                return
            if not turn.is_active:
                yield _format_turn_completed(turn)
                return
            maybe_start_runner(force=True)
            while True:
                turn = current_turn()
                if turn is None:
                    return
                if not turn.is_active:
                    yield _format_turn_completed(turn)
                    return
                with get_session_with_current_tenant() as stream_db_session:
                    session = get_build_session(session_id, user_id, stream_db_session)
                    if session is None:
                        yield _format_stream_error("Session not found")
                        return
                    sandbox = get_sandbox_by_user_id(stream_db_session, user_id)
                    if (
                        session.opencode_session_id
                        and sandbox is not None
                        and sandbox.status.is_active()
                    ):
                        break
                yield SSE_KEEPALIVE
                maybe_start_runner()
                time.sleep(POLL_INTERVAL_SECONDS)

            terminal_packet_seen = False
            with get_session_with_current_tenant() as stream_db_session:
                session_manager = SessionManager(stream_db_session)
                with closing(
                    session_manager.subscribe_to_existing_session_events(
                        session_id,
                        user_id,
                        keepalive_seconds=LIVE_STREAM_KEEPALIVE_SECONDS,
                    )
                ) as chunks:
                    for chunk in chunks:
                        turn = current_turn()
                        if turn is None:
                            return
                        # The session stream can already contain a successor's events.
                        # Saved history supplies any unrendered tail of this turn.
                        if not turn.is_active:
                            break
                        chunk_type = _stream_chunk_type(chunk)
                        if chunk_type in TERMINAL_STREAM_EVENT_TYPES:
                            terminal_packet_seen = True
                            break
                        yield chunk
                        maybe_start_runner()

            # Release the live subscription and database connection before waiting.
            deadline = time.monotonic() + TURN_COMPLETION_WAIT_SECONDS
            while True:
                turn = current_turn()
                if turn is None:
                    return
                if not turn.is_active:
                    yield _format_turn_completed(turn)
                    return
                if not terminal_packet_seen or time.monotonic() >= deadline:
                    return
                maybe_start_runner()
                # Yield during the short tail so disconnects release the stream promptly.
                yield SSE_KEEPALIVE
                time.sleep(TURN_COMPLETION_CHECK_SECONDS)
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
