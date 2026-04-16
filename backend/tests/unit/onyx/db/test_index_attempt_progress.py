from datetime import datetime
from datetime import timedelta
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import transition_attempt_to_in_progress
from onyx.db.indexing_coordination import IndexingCoordination


class _ScalarOneResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


def test_transition_attempt_to_in_progress_resets_stall_tracking() -> None:
    old_time = datetime.now(timezone.utc) - timedelta(hours=7)
    attempt = SimpleNamespace(
        status=IndexingStatus.NOT_STARTED,
        time_started=None,
        last_progress_time=old_time,
        last_batches_completed_count=3,
        heartbeat_counter=11,
        last_heartbeat_time=old_time,
        last_heartbeat_value=5,
    )
    db_session = MagicMock()
    db_session.execute.return_value = _ScalarOneResult(attempt)

    result = transition_attempt_to_in_progress(17, db_session)

    assert result is attempt
    assert attempt.status == IndexingStatus.IN_PROGRESS
    assert attempt.time_started is not None
    assert attempt.last_progress_time is None
    assert attempt.last_batches_completed_count == 0
    assert attempt.last_heartbeat_time is None
    assert attempt.last_heartbeat_value == 11
    db_session.commit.assert_called_once()


def test_update_progress_tracking_treats_reset_attempt_as_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    attempt = SimpleNamespace(
        last_progress_time=now - timedelta(hours=7),
        last_batches_completed_count=0,
    )
    db_session = MagicMock()

    monkeypatch.setattr(
        "onyx.db.indexing_coordination.get_index_attempt",
        lambda _db_session, _attempt_id: attempt,
    )
    monkeypatch.setattr(
        "onyx.db.indexing_coordination.get_db_current_time",
        lambda _db_session: now,
    )

    assert (
        IndexingCoordination.update_progress_tracking(
            db_session,
            index_attempt_id=17,
            current_batches_completed=0,
            timeout_hours=6,
        )
        is False
    )

    attempt.last_progress_time = None

    assert (
        IndexingCoordination.update_progress_tracking(
            db_session,
            index_attempt_id=17,
            current_batches_completed=0,
            timeout_hours=6,
        )
        is True
    )
    assert attempt.last_progress_time == now
    assert attempt.last_batches_completed_count == 0
    db_session.commit.assert_called_once()
