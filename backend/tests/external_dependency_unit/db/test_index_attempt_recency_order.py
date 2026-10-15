"""The IndexAttempt recency helpers must order by `time_created`, never
`time_updated`.

`time_updated` carries `onupdate=func.now()`, so any background write to an
old attempt moves it. Checkpoint cleanup does that when it nulls
`checkpoint_pointer` on attempts older than a week. Ordering by
`time_created` keeps such a write from making an old attempt look like the
latest one and deferring the next scheduled run.
"""

from collections.abc import Callable, Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import (
    get_last_attempt_for_cc_pair,
    get_recent_attempts_for_cc_pair,
    get_recent_completed_attempts_for_cc_pair,
)
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_OLDER = datetime(2026, 1, 1, tzinfo=timezone.utc)
_NEWER = datetime(2026, 1, 10, tzinfo=timezone.utc)

RecentAttemptsQuery = Callable[[int, int, int, Session], list[IndexAttempt]]


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _make_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    *,
    time_created: datetime,
) -> IndexAttempt:
    """A successful attempt pinned to `time_created`, `time_updated` to match."""
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.SUCCESS,
        time_created=time_created,
        time_updated=time_created,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def _make_newest_and_touched_older(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> tuple[IndexAttempt, IndexAttempt]:
    """Two attempts where the older one got a later background write, so its
    `time_updated` moved past the newer one through `onupdate`."""
    newest = _make_attempt(db_session, cc_pair, time_created=_NEWER)
    older = _make_attempt(db_session, cc_pair, time_created=_OLDER)
    older.error_msg = "touched by a background task"
    db_session.commit()
    db_session.refresh(older)
    assert older.time_updated > newest.time_updated
    return newest, older


def test_last_attempt_ignores_a_later_time_updated(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    newest, _ = _make_newest_and_touched_older(db_session, cc_pair)

    result = get_last_attempt_for_cc_pair(
        cc_pair.id, newest.search_settings_id, db_session
    )

    assert result is not None
    assert result.id == newest.id


@pytest.mark.parametrize(
    "query",
    [get_recent_attempts_for_cc_pair, get_recent_completed_attempts_for_cc_pair],
)
def test_recent_attempts_order_by_time_created(
    db_session: Session, cc_pair: ConnectorCredentialPair, query: RecentAttemptsQuery
) -> None:
    newest, older = _make_newest_and_touched_older(db_session, cc_pair)

    results = query(cc_pair.id, newest.search_settings_id, 10, db_session)

    assert [attempt.id for attempt in results] == [newest.id, older.id]
