"""The chat page's suggested questions. Every chat open asks for them; a click
marks one used, so it is not shown to that person again."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_chat_accessible_user
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.suggested_questions.models import (
    PersonSuggestions,
    SuggestionsState,
)
from onyx.server.features.suggested_questions.ranking import get_suggestions
from onyx.server.features.suggested_questions.scheduling import is_enabled
from onyx.server.features.suggested_questions.store import mark_used, record_seen
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/chat/suggested-questions")

_NONE = PersonSuggestions(questions=[], state=SuggestionsState.READY)


class MarkUsedRequest(BaseModel):
    question_id: str


@router.get("")
def get_suggested_questions(
    agent_id: int,
    seed: int,
    poll: bool = False,
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> PersonSuggestions:
    """Called on every chat open, whatever the agent, so the visit is recorded:
    pool runs cover people who used the chat recently. Questions are only for
    the default agent; a custom agent keeps its own starter messages. `seed` is
    made once per page load, so the questions stay put while the page is open;
    `poll` marks the re-fetches while the page shows "preparing", which only
    read."""
    if user.is_anonymous:
        return _NONE
    now = datetime.now(UTC)
    if agent_id != DEFAULT_PERSONA_ID:
        if not poll and _enabled():
            record_seen(user.id, now)
        return _NONE
    return get_suggestions(
        db_session, user, get_current_tenant_id(), seed=seed, poll=poll, now=now
    )


@router.post("/used")
def mark_suggested_question_used(
    request: MarkUsedRequest,
    user: User = Depends(current_chat_accessible_user),
) -> None:
    if user.is_anonymous or not _enabled():
        return
    mark_used(user.id, request.question_id)


def _enabled() -> bool:
    try:
        return is_enabled()
    except Exception:
        logger.warning("Suggested questions: trial status unknown", exc_info=True)
        return False
