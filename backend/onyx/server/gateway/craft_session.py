"""Attribute gateway calls to the Craft session that made them.

The per-session opencode config sends ``CRAFT_SESSION_HEADER`` on every LLM
call. The gateway checks the session belongs to the calling user and then tags
its traces with it, so a session's LLM calls can be found by one filter.
"""

from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.gateway.configs import CRAFT_SESSION_HEADER
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace
from onyx.utils.logger import setup_logger

logger = setup_logger()


def resolve_craft_session_id(
    http_request: Request, user: User, db_session: Session
) -> str | None:
    """The verified Craft session id on this request, or ``None``.

    A missing header is the normal case for non-Craft gateway clients. A
    malformed or foreign id is dropped, never trusted: the sandbox can edit its
    own config, so the header is an attribution hint, not an identity claim.
    """
    raw = http_request.headers.get(CRAFT_SESSION_HEADER)
    if not raw:
        return None
    try:
        session_id = UUID(raw)
    except ValueError:
        logger.warning("Ignoring malformed %s header", CRAFT_SESSION_HEADER)
        return None
    if get_build_session(session_id, user.id, db_session) is None:
        logger.warning(
            "Ignoring %s header for a session the caller does not own",
            CRAFT_SESSION_HEADER,
        )
        return None
    return str(session_id)


def llm_gateway_trace(
    flow: LLMFlow, model: str, craft_session_id: str | None = None
) -> Trace:
    """One trace per gateway call; grouped by Craft session when known."""
    metadata: dict[str, str] = {"flow": flow.value, "model": model}
    if craft_session_id is not None:
        metadata["craft_session_id"] = craft_session_id
    return trace("llm_gateway", group_id=craft_session_id, metadata=metadata)
