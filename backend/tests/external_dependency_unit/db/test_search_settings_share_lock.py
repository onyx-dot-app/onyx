"""The share lock the content-hash stamp relies on (onyx.db.search_settings
.lock_search_settings_for_share): a status flip waits for every holder, and a
holder that locks again after the flip reads the new status, not a cached row."""

import contextvars
import threading
import time
from collections.abc import Generator

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexModelStatus
from onyx.db.models import SearchSettings
from onyx.db.search_settings import lock_search_settings_for_share
from tests.external_dependency_unit.indexing_helpers import (
    make_future_search_settings,
)


@pytest.fixture
def settings_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[SearchSettings, None, None]:
    row = make_future_search_settings(db_session)
    try:
        yield row
    finally:
        db_session.rollback()
        db_session.execute(delete(SearchSettings).where(SearchSettings.id == row.id))
        db_session.commit()


def _flip_is_blocked(db_session: Session, timeout: float = 5.0) -> bool:
    """Another backend waits on a lock this session holds (pg_locks is readable
    without privileges, unlike other sessions' rows in pg_stat_activity)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waiting = db_session.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE NOT granted "
                "AND pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ).scalar_one()
        if waiting:
            return True
        time.sleep(0.1)
    return False


def test_status_flip_waits_for_the_lock_and_is_read_afterwards(
    db_session: Session, settings_row: SearchSettings
) -> None:
    # The batch's session already holds the row (loaded before the lock).
    cached = db_session.get(SearchSettings, settings_row.id)
    assert cached is not None and cached.status == IndexModelStatus.FUTURE
    locked = lock_search_settings_for_share(db_session, settings_row.id)
    assert locked is not None and locked.status == IndexModelStatus.FUTURE

    started = threading.Event()
    flipped = threading.Event()

    def flip() -> None:
        with get_session_with_current_tenant() as other:
            started.set()
            other.execute(
                update(SearchSettings)
                .where(SearchSettings.id == settings_row.id)
                .values(status=IndexModelStatus.PAST)
            )
            other.commit()
        flipped.set()

    thread = threading.Thread(target=contextvars.copy_context().run, args=(flip,))
    thread.start()
    try:
        # The flip blocks on the share lock, and lands once it is released.
        assert started.wait(5.0)
        assert _flip_is_blocked(db_session), "the status flip did not wait"
        assert not flipped.is_set()
        db_session.commit()
        assert flipped.wait(10.0)
    finally:
        thread.join(timeout=10.0)

    # Locking again reads the flipped status, not the row cached in the session.
    relocked = lock_search_settings_for_share(db_session, settings_row.id)
    assert relocked is not None and relocked.status == IndexModelStatus.PAST
    db_session.commit()
