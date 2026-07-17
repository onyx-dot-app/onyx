"""Guards the INTERRUPTED reclassification: an attempt stopped mid-run by
infrastructure (deploy / autoscaling) must not count as a failure, so it never
trips the repeated-error auto-pause, while genuine consecutive FAILED still does.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.background.celery.tasks.docprocessing.utils import is_in_repeated_error_state
from onyx.background.celery.tasks.docprocessing.utils import (
    NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE,
)
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import mark_attempt_interrupted

_UTILS = "onyx.background.celery.tasks.docprocessing.utils"


def _attempt(status: IndexingStatus) -> MagicMock:
    attempt = MagicMock()
    attempt.status = status
    return attempt


def _cc_pair(refresh_freq: int | None = 3600) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 1
    cc_pair.connector.refresh_freq = refresh_freq
    return cc_pair


def test_interrupted_is_terminal_but_not_a_failure() -> None:
    assert IndexingStatus.INTERRUPTED.is_terminal() is True
    assert IndexingStatus.INTERRUPTED.is_successful() is False
    assert IndexingStatus.INTERRUPTED != IndexingStatus.FAILED


@patch(f"{_UTILS}.get_recent_attempts_for_cc_pair")
def test_consecutive_failed_is_repeated_error(mock_recent: MagicMock) -> None:
    mock_recent.return_value = [
        _attempt(IndexingStatus.FAILED)
        for _ in range(NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE)
    ]
    assert (
        is_in_repeated_error_state(
            _cc_pair(), search_settings_id=1, db_session=MagicMock()
        )
        is True
    )


@patch(f"{_UTILS}.get_recent_attempts_for_cc_pair")
def test_interrupted_breaks_the_failed_streak(mock_recent: MagicMock) -> None:
    # A single infra interruption anywhere in the recent window keeps the
    # connector out of the repeated-error state, so a deploy/scale-down burst
    # never auto-pauses it.
    attempts = [
        _attempt(IndexingStatus.FAILED)
        for _ in range(NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE - 1)
    ]
    attempts.append(_attempt(IndexingStatus.INTERRUPTED))
    mock_recent.return_value = attempts
    assert (
        is_in_repeated_error_state(
            _cc_pair(), search_settings_id=1, db_session=MagicMock()
        )
        is False
    )


def test_mark_attempt_interrupted_skips_already_terminal() -> None:
    # TOCTOU guard: if the locked row is already terminal (e.g. the subprocess
    # finished SUCCESS just as shutdown began), the mark is a no-op, not a clobber.
    attempt = MagicMock()
    attempt.status = IndexingStatus.SUCCESS
    db_session = MagicMock()
    db_session.execute.return_value.scalar_one.return_value = attempt

    mark_attempt_interrupted(1, db_session, "worker shutting down")

    assert attempt.status == IndexingStatus.SUCCESS
    db_session.commit.assert_not_called()
