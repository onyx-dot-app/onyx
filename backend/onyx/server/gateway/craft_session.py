"""Attribute gateway calls to the Craft session that made them.

The per-session opencode config sends ``CRAFT_SESSION_HEADER`` on every LLM
call. A request-scoped dependency verifies the session belongs to the caller
and binds it to a context variable; the trace helper reads it from there. The
variable travels into the stream worker threads with the rest of the request
context (``start_thread_with_context``), so nothing in between has to carry it.
"""

from collections.abc import AsyncIterator, Callable, Coroutine
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.gateway.configs import CRAFT_SESSION_HEADER
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace
from onyx.utils.logger import setup_logger

logger = setup_logger()

CRAFT_SESSION_ID_CONTEXTVAR: ContextVar[str | None] = ContextVar(
    "craft_session_id", default=None
)


def resolve_craft_session_id(
    http_request: Request, user: User, db_session: Session
) -> str | None:
    """The verified Craft session id on this request, or ``None``.

    A missing header is the normal case for non-Craft gateway clients. A
    malformed or foreign id is dropped, never trusted: the sandbox can edit its
    own config, so the header is an attribution hint, not an identity claim.
    """
    # ``db_session`` is the request's database connection; the Craft session
    # is the build session row the header names.
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
        db_session: Session = Depends(get_session),
    ) -> AsyncIterator[None]:
        craft_session_id = await run_in_threadpool(
            resolve_craft_session_id, http_request, user, db_session
        )
        token = CRAFT_SESSION_ID_CONTEXTVAR.set(craft_session_id)
        try:
            yield
        finally:
            CRAFT_SESSION_ID_CONTEXTVAR.reset(token)

    return bind_craft_session


def llm_gateway_trace(flow: LLMFlow, model: str) -> Trace:
    """One trace per gateway call, tagged with the bound Craft session if any."""
    metadata: dict[str, str] = {"flow": flow.value, "model": model}
    craft_session_id = CRAFT_SESSION_ID_CONTEXTVAR.get()
    if craft_session_id is not None:
        metadata["craft_session_id"] = craft_session_id
    return trace("llm_gateway", metadata=metadata)
