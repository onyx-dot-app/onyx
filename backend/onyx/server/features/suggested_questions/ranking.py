"""The questions a person sees when they open the chat, and the run a chat open
asks for when the person is short of questions."""

import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from onyx.access.access import get_censoring_enabled_sources
from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.suggested_questions import get_visible_document_ids, has_visible_documents
from onyx.server.features.suggested_questions.config import (
    SQ_PREPARING_S,
    SQ_PRIVATE_REFILL_AT,
    SQ_SHARED_REFRESH_AT,
    SQ_SHOWN,
)
from onyx.server.features.suggested_questions.models import (
    PersonSuggestions,
    PoolQuestion,
    QuestionPool,
    RefreshReason,
    ShownQuestion,
    SuggestionsState,
    UserRecord,
)
from onyx.server.features.suggested_questions.scheduling import (
    fresh_document_ids,
    is_enabled,
    request_pool_refresh,
    request_user_topup,
    topup_allowed,
)
from onyx.server.features.suggested_questions.selection import choose_documents
from onyx.server.features.suggested_questions.store import (
    load_pool,
    load_user_record,
    record_requested,
    record_seen,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_suggestions(
    db_session: Session,
    user: User,
    tenant_id: str,
    seed: int,
    poll: bool,
    now: datetime,
) -> PersonSuggestions:
    """Up to SQ_SHOWN questions this person may open right now, private first.
    A chat open records the visit and asks for the run the person needs; a
    poll while the page shows "preparing" only reads."""
    try:
        enabled = is_enabled()
    except Exception:
        logger.warning("Suggested questions: trial status unknown", exc_info=True)
        enabled = False
    if not enabled:
        return PersonSuggestions(questions=[], state=SuggestionsState.READY)

    record = load_user_record(user.id) if poll else record_seen(user.id, now)
    pool = load_pool() or QuestionPool()
    external_group_ids = get_user_external_group_ids(db_session, user)
    censored_sources = get_censoring_enabled_sources()
    visible = get_visible_document_ids(
        db_session,
        user,
        external_group_ids,
        list({q.document_id for q in [*pool.questions, *record.questions]}),
        censored_sources,
    )
    shared = usable_questions(pool.questions, record, visible, now)
    private = usable_questions(record.questions, record, visible, now)

    if not poll and _request_run(tenant_id, user, record, shared, private, now):
        try:
            record = record_requested(user.id, now)
        except Exception:
            # The run is queued; only the "preparing" hint is lost.
            logger.warning(
                "Suggested questions: could not record the request", exc_info=True
            )

    shown = pick_questions(private, shared, seed)
    if len(shown) >= SQ_SHOWN:
        state = SuggestionsState.READY
    elif record.requested_at is not None and now - record.requested_at < timedelta(
        seconds=SQ_PREPARING_S
    ):
        state = SuggestionsState.PREPARING
    elif not shown and not has_visible_documents(
        db_session, user, external_group_ids, censored_sources
    ):
        state = SuggestionsState.NO_DOCUMENTS
    else:
        state = SuggestionsState.READY
    return PersonSuggestions(questions=shown, state=state)


def usable_questions(
    questions: list[PoolQuestion],
    record: UserRecord,
    visible_document_ids: set[str],
    now: datetime,
) -> list[PoolQuestion]:
    """Questions the person has not used, about a document they may open,
    young enough to show."""
    used = set(record.used)
    return [
        question
        for question in questions
        if question.id not in used
        and question.document_id in visible_document_ids
        and question.is_fresh(now)
    ]


def pick_questions(
    private: list[PoolQuestion], shared: list[PoolQuestion], seed: int
) -> list[ShownQuestion]:
    """Up to SQ_SHOWN of the usable questions, private first, one per document.
    The page sends one seed per page load, so the pick stays the same while the
    page is open and changes on the next load."""
    # TODO(ENG-4481): rank by use-case fit once the company use case is stored.
    rng = random.Random(seed)  # noqa: S311 - a shuffle, not a secret
    # A fixed order first: shelf order can change between polls.
    mine = sorted(private, key=lambda q: q.id)
    everyone = sorted(shared, key=lambda q: q.id)
    rng.shuffle(mine)
    rng.shuffle(everyone)
    shown: list[ShownQuestion] = []
    seen_documents: set[str] = set()
    for question, is_private in [
        *((q, True) for q in mine),
        *((q, False) for q in everyone),
    ]:
        if question.document_id in seen_documents:
            continue
        seen_documents.add(question.document_id)
        shown.append(
            ShownQuestion(id=question.id, message=question.text, private=is_private)
        )
        if len(shown) == SQ_SHOWN:
            break
    return shown


def _request_run(
    tenant_id: str,
    user: User,
    record: UserRecord,
    shared: list[PoolQuestion],
    private: list[PoolQuestion],
    now: datetime,
) -> bool:
    """Ask for the run this person needs. Short of shared questions: a pool
    run, which also fills private shelves where it can. Otherwise, or when no
    pool run is allowed now, a top-up when their private shelf runs low. A
    top-up that would find nothing new is never queued. Never raises: the chat
    page must not fail because of a run request, so its queries use their own
    session: a failed one cannot break the page's session. Returns whether a
    run is queued for the person."""
    try:
        if len(shared) <= SQ_SHARED_REFRESH_AT and request_pool_refresh(
            tenant_id, RefreshReason.PERSON_SHORT, requester_id=user.id
        ):
            return True
        if len(private) > SQ_PRIVATE_REFILL_AT or not topup_allowed(record, now):
            return False
        with get_session_with_current_tenant() as db_session:
            candidates = choose_documents(
                db_session,
                [user],
                set(),
                {user.id: fresh_document_ids(record.questions, now)},
                include_shared=False,
            )
        return bool(candidates) and request_user_topup(tenant_id, user.id, record, now)
    except Exception:
        logger.exception("Suggested questions: could not ask for a run")
        return False
