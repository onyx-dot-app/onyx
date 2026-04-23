"""External dependency unit tests for `get_old_index_attempt_ids`.

Validates the cleanup-query logic against real Postgres:

- Short-circuits (returns []) when no rows exist OR when the oldest row is
  within the retention window. The short-circuit relies on the index on
  `time_created` to avoid the full-table window-function scan that dominated
  AAS on the cloud cluster.
- When stale rows exist, returns their IDs while retaining the most recent
  NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP per (cc_pair, search_settings) group.
- Returns plain `int`s, not hydrated ORM objects.
"""

from collections.abc import Generator
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.background.indexing.index_attempt_utils import get_old_index_attempt_ids
from onyx.background.indexing.index_attempt_utils import (
    NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP,
)
from onyx.configs.constants import NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        # index_attempt has no ON DELETE CASCADE from cc_pair; drop first.
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _make_attempt(
    db_session: Session,
    cc_pair_id: int,
    days_old: float,
) -> int:
    """Insert an IndexAttempt whose `time_created` is `days_old` days before db now."""
    target_time = get_db_current_time(db_session) - timedelta(days=days_old)
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=None,
        from_beginning=False,
        status=IndexingStatus.NOT_STARTED,
    )
    db_session.add(attempt)
    db_session.flush()
    # server_default=func.now() fires on INSERT; override to the target time.
    db_session.execute(
        update(IndexAttempt)
        .where(IndexAttempt.id == attempt.id)
        .values(time_created=target_time)
    )
    db_session.commit()
    return attempt.id


class TestShortCircuit:
    def test_no_attempts_returns_empty(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,  # noqa: ARG002
    ) -> None:
        assert get_old_index_attempt_ids(db_session) == []

    def test_all_recent_returns_empty(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
    ) -> None:
        for _ in range(15):
            _make_attempt(db_session, cc_pair.id, days_old=1)

        assert get_old_index_attempt_ids(db_session) == []


class TestWindowQuery:
    def test_old_beyond_keep_count_returned(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
    ) -> None:
        recent_days = max(1, NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS - 1)
        old_days = NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS + 1

        for _ in range(NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP):
            _make_attempt(db_session, cc_pair.id, days_old=recent_days)

        old_ids: list[int] = [
            _make_attempt(db_session, cc_pair.id, days_old=old_days) for _ in range(3)
        ]

        result = get_old_index_attempt_ids(db_session)
        assert sorted(result) == sorted(old_ids)
        assert all(isinstance(i, int) for i in result)

    def test_old_within_keep_count_not_returned(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
    ) -> None:
        # Fewer rows than NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP: even if every one
        # of them is past the retention window, none are eligible because the
        # rank filter (rank > keep_count) excludes them all.
        old_days = NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS + 5
        for _ in range(5):
            _make_attempt(db_session, cc_pair.id, days_old=old_days)

        assert get_old_index_attempt_ids(db_session) == []
