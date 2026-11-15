"""Guards the repeated-error flag: a connector with no refresh frequency is
flagged after one failure and its alert says it failed, not that it failed
repeatedly, and an attempt an admin resolved breaks the failed streak."""

from unittest.mock import MagicMock, patch

from onyx.background.celery.tasks.docprocessing.utils import (
    NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE,
    failures_before_repeated_error_state,
    is_in_repeated_error_state,
    repeated_error_alert,
)
from onyx.db.enums import CCPairRunKind, IndexingStatus

_UTILS = "onyx.background.celery.tasks.docprocessing.utils"


def _attempt(attempt_id: int) -> MagicMock:
    attempt = MagicMock()
    attempt.id = attempt_id
    attempt.status = IndexingStatus.FAILED
    return attempt


def _cc_pair(refresh_freq: int | None) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = 1
    cc_pair.connector.refresh_freq = refresh_freq
    return cc_pair


def test_one_failure_flags_a_connector_without_a_refresh_frequency() -> None:
    assert failures_before_repeated_error_state(_cc_pair(None).connector) == 1
    assert (
        failures_before_repeated_error_state(_cc_pair(3600).connector)
        == NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
    )


def test_the_alert_says_failed_after_one_failure() -> None:
    title, description = repeated_error_alert("Wiki", "confluence", 1)

    assert "repeated" not in title.lower()
    assert "repeatedly" not in description.lower()
    assert "Wiki" in title
    assert "confluence" in description


def test_the_alert_says_failed_repeatedly_after_several_failures() -> None:
    title, description = repeated_error_alert(
        "Wiki", "confluence", NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
    )

    assert "repeated error state" in title
    assert "failed repeatedly" in description


@patch(f"{_UTILS}.get_resolution_times")
@patch(f"{_UTILS}.get_recent_attempts_for_cc_pair")
def test_a_resolved_failure_breaks_the_streak(
    mock_recent: MagicMock, mock_resolutions: MagicMock
) -> None:
    mock_recent.return_value = [_attempt(7)]
    mock_resolutions.return_value = {(CCPairRunKind.INDEXING, 7): MagicMock()}

    assert (
        is_in_repeated_error_state(
            _cc_pair(None), search_settings_id=1, db_session=MagicMock()
        )
        is False
    )


@patch(f"{_UTILS}.get_resolution_times")
@patch(f"{_UTILS}.get_recent_attempts_for_cc_pair")
def test_an_unresolved_failure_still_flags(
    mock_recent: MagicMock, mock_resolutions: MagicMock
) -> None:
    mock_recent.return_value = [_attempt(7)]
    mock_resolutions.return_value = {}

    assert (
        is_in_repeated_error_state(
            _cc_pair(None), search_settings_id=1, db_session=MagicMock()
        )
        is True
    )
