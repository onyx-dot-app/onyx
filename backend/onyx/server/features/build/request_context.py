"""Verify Craft session attribution for model and search API requests.

The sandbox config and egress proxy send a session hint. The API checks its
ownership before binding it to request context, which follows stream workers.
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
from onyx.server.features.build.configs import CRAFT_SESSION_HEADER
from onyx.server.features.build.turn_tracing import get_craft_turn_trace_id
from onyx.utils.logger import setup_logger

logger = setup_logger()

CRAFT_SESSION_ID_CONTEXTVAR: ContextVar[str | None] = ContextVar(
    "craft_session_id", default=None
)


def _claimed_session_id(http_request: Request) -> UUID | None:
    claimed = http_request.headers.get(CRAFT_SESSION_HEADER)
    if not claimed:
        return None
    try:
        return UUID(claimed)
    except ValueError:
        logger.warning("Ignoring malformed %s header", CRAFT_SESSION_HEADER)
        return None


def resolve_craft_session_id(
    claimed: UUID, user: User, db_session: Session
) -> str | None:
    """The sandbox's attribution hint is valid only for the authenticated owner."""
    if get_build_session(claimed, user.id, db_session) is None:
        logger.warning(
            "Ignoring %s header for a Craft session the caller does not own",
            CRAFT_SESSION_HEADER,
        )
        return None
    return str(claimed)


def _resolve_owned_session(claimed: UUID, user: User) -> str | None:
    with get_session_with_current_tenant() as db_session:
        return resolve_craft_session_id(claimed, user, db_session)


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
        claimed = _claimed_session_id(http_request)
        craft_session_id = (
            await run_in_threadpool(_resolve_owned_session, claimed, user)
            if claimed is not None
            else None
        )
        token = CRAFT_SESSION_ID_CONTEXTVAR.set(craft_session_id)
        try:
            yield
        finally:
            CRAFT_SESSION_ID_CONTEXTVAR.reset(token)

    return bind_craft_session


def craft_trace_metadata(*, include_turn: bool = True) -> dict[str, str]:
    """Resolve turn context only when a verified request opens a trace."""
    session_id = CRAFT_SESSION_ID_CONTEXTVAR.get()
    if session_id is None:
        return {}
    metadata = {"craft_session_id": session_id}
    if include_turn:
        turn_id = get_craft_turn_trace_id(UUID(session_id))
        if turn_id is not None:
            metadata["distributed_trace_id"] = turn_id
            metadata["distributed_parent_span_id"] = turn_id[:16]
    return metadata
