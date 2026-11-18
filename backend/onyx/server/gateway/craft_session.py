"""Attribute gateway calls to the Craft session that made them.

The per-session opencode config sends ``CRAFT_SESSION_HEADER`` on every LLM
call. A request-scoped dependency verifies the session belongs to the caller
and binds it to a context variable; ``onyx.server.gateway.tracing`` reads it
when it opens a trace. The variable travels into the stream worker threads with
the rest of the request context (``start_thread_with_context``), so nothing in
between has to carry it.
"""

from collections.abc import AsyncIterator, Callable, Coroutine
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from onyx.db.build_session import get_build_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.server.features.build.turn_tracing import get_craft_turn_trace_id
from onyx.server.gateway.configs import CRAFT_SESSION_HEADER
from onyx.utils.logger import setup_logger

logger = setup_logger()

CRAFT_SESSION_ID_CONTEXTVAR: ContextVar[str | None] = ContextVar(
    "craft_session_id", default=None
)

CRAFT_TURN_TRACE_ID_CONTEXTVAR: ContextVar[str | None] = ContextVar(
    "craft_turn_trace_id", default=None
)


def resolve_craft_session_id(
    http_request: Request, user: User, db_session: Session
) -> str | None:
    """The verified Craft session id on this request, or ``None``.

    A missing header is the normal case for non-Craft gateway clients. A
    malformed or foreign id is dropped, never trusted: the sandbox can edit its
    own config, so the header is an attribution hint, not an identity claim.
    """
    # The Craft session is the build session row the header names.
    claimed = http_request.headers.get(CRAFT_SESSION_HEADER)
    if not claimed:
        return None
    try:
        craft_session_id = UUID(claimed)
    except ValueError:
        logger.warning("Ignoring malformed %s header", CRAFT_SESSION_HEADER)
        return None
    # Ownership check only: the row is looked up, not created or changed.
    owned = get_build_session(craft_session_id, user.id, db_session) is not None
    if not owned:
        logger.warning(
            "Ignoring %s header for a Craft session the caller does not own",
            CRAFT_SESSION_HEADER,
        )
        return None
    return str(craft_session_id)


def _resolve_craft_trace_context(
    http_request: Request, user: User
) -> tuple[str | None, str | None]:
    # Release the ownership connection before the PostgreSQL cache checks out one.
    with get_session_with_current_tenant() as db_session:
        session_id = resolve_craft_session_id(http_request, user, db_session)
    turn_trace_id = (
        get_craft_turn_trace_id(UUID(session_id)) if session_id is not None else None
    )
    return session_id, turn_trace_id


def craft_session_binder(
    user_dependency: Callable[..., Coroutine[Any, Any, User]],
) -> Callable[..., AsyncIterator[None]]:
    """A router dependency that binds the request's Craft session for tracing.

    Takes the router's own user dependency so FastAPI resolves the user once
    per request. It must be async: a sync dependency runs on a threadpool copy
    of the request context, and a value set there never reaches the response.
    """

    async def bind_craft_session(
        http_request: Request,
        user: User = Depends(user_dependency),
    ) -> AsyncIterator[None]:
        craft_session_id, turn_trace_id = await run_in_threadpool(
            _resolve_craft_trace_context, http_request, user
        )
        token = CRAFT_SESSION_ID_CONTEXTVAR.set(craft_session_id)
        turn_token = CRAFT_TURN_TRACE_ID_CONTEXTVAR.set(turn_trace_id)
        try:
            yield
        finally:
            CRAFT_TURN_TRACE_ID_CONTEXTVAR.reset(turn_token)
            CRAFT_SESSION_ID_CONTEXTVAR.reset(token)

    return bind_craft_session
