"""The share lock the content-hash stamp relies on (onyx.db.search_settings
.lock_search_settings_for_share): a status flip waits for every holder, and a
holder that locks again after the flip reads the new status, not a cached row."""

import contextvars
import threading
from collections.abc import Generator

import pytest
from sqlalchemy import delete, update
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


def test_status_flip_waits_for_the_lock_and_is_read_afterwards(
    db_session: Session, settings_row: SearchSettings
) -> None:
    # The batch's session already holds the row (loaded before the lock).
    cached = db_session.get(SearchSettings, settings_row.id)
    assert cached is not None and cached.status == IndexModelStatus.FUTURE
    locked = lock_search_settings_for_share(db_session, settings_row.id)
    assert locked is not None and locked.status == IndexModelStatus.FUTURE

    flipped = threading.Event()

    def flip() -> None:
        with get_session_with_current_tenant() as other:
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
        # The flip waits while the share lock is held, and lands once it is released.
        assert not flipped.wait(1.0)
        db_session.commit()
        assert flipped.wait(10.0)
    finally:
        thread.join(timeout=10.0)

    # Locking again reads the flipped status, not the row cached in the session.
    relocked = lock_search_settings_for_share(db_session, settings_row.id)
    assert relocked is not None and relocked.status == IndexModelStatus.PAST
    db_session.commit()
