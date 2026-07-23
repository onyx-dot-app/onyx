import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.chat_search import search_chat_sessions
from onyx.db.models import ChatSession
from onyx.db.models import User
from tests.external_dependency_unit.conftest import create_test_user

SHARED_TIME = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _make_tied_sessions(
    db_session: Session, user: User, count: int, description: str
) -> set[UUID]:
    """Create ``count`` sessions that all share ``SHARED_TIME`` so the only
    thing keeping OFFSET/LIMIT pages disjoint is a unique ORDER BY tiebreaker."""
    created_ids: set[UUID] = set()
    for _ in range(count):
        chat_session = ChatSession(
            user_id=user.id,
            description=description,
            time_created=SHARED_TIME,
        )
        db_session.add(chat_session)
        db_session.flush()
        created_ids.add(chat_session.id)
    return created_ids


def _paginate_all(
    db_session: Session, user_id: UUID, query: str | None, page_size: int
) -> list[UUID]:
    """Walk every page via search_chat_sessions, collecting ids in order."""
    collected: list[UUID] = []
    page = 1
    while True:
        sessions, has_more = search_chat_sessions(
            user_id=user_id,
            db_session=db_session,
            query=query,
            page=page,
            page_size=page_size,
        )
        collected.extend(s.id for s in sessions)
        if not has_more:
            break
        page += 1
        # Safety valve so a pagination bug can't loop forever.
        assert page < 100
    return collected


def test_recent_pagination_stable_with_tied_timestamps(db_session: Session) -> None:
    """No-query branch: tied ``time_created`` must paginate without cross-page
    duplicates, without omissions, and in a deterministic order."""
    user = create_test_user(db_session, "chat-search-recent")
    created_ids = _make_tied_sessions(db_session, user, count=25, description="recent")

    try:
        all_ids = _paginate_all(db_session, user.id, query=None, page_size=10)

        # The reported bug: no session repeats across pages.
        assert len(all_ids) == len(set(all_ids)), "duplicate session(s) across pages"
        # Flip side of the same defect: nothing silently dropped.
        assert set(all_ids) == created_ids
        # Total, deterministic order: time_created DESC, then id DESC.
        assert all_ids == sorted(created_ids, reverse=True)
    finally:
        db_session.rollback()


def test_query_pagination_stable_with_tied_timestamps(db_session: Session) -> None:
    """Search branch: full-text matches with tied ``time_created`` must paginate
    without cross-page duplicates, without omissions, and in a deterministic order."""
    user = create_test_user(db_session, "chat-search-query")
    created_ids = _make_tied_sessions(
        db_session, user, count=25, description="quarterly alpaca report"
    )

    try:
        all_ids = _paginate_all(db_session, user.id, query="alpaca", page_size=10)

        assert len(all_ids) == len(set(all_ids)), "duplicate session(s) across pages"
        assert set(all_ids) == created_ids
        assert all_ids == sorted(created_ids, reverse=True)
    finally:
        db_session.rollback()
