import pytest

from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    _check_external_group_failure_threshold,
)
from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    ExternalGroupSyncFailureThresholdError,
)
from ee.onyx.db.external_perm import ExternalGroupSyncFailure


def _failure(full_exception_trace: str | None = None) -> ExternalGroupSyncFailure:
    return ExternalGroupSyncFailure(
        external_group_id="group-id",
        external_group_name="group-name",
        failure_message="group sync failed",
        full_exception_trace=full_exception_trace,
    )


def test_external_group_failure_threshold_allows_safe_failure_count() -> None:
    _check_external_group_failure_threshold(
        total_failures=1,
        total_groups_seen=20,
        last_failure=_failure(),
    )


def test_external_group_failure_threshold_aborts_when_count_exceeded() -> None:
    with pytest.raises(RuntimeError, match="too many group-level errors"):
        _check_external_group_failure_threshold(
            total_failures=4,
            total_groups_seen=100,
            last_failure=_failure(),
        )


def test_external_group_failure_threshold_aborts_when_ratio_exceeded() -> None:
    with pytest.raises(RuntimeError, match="too many group-level errors"):
        _check_external_group_failure_threshold(
            total_failures=1,
            total_groups_seen=5,
            last_failure=_failure(),
        )


def test_external_group_failure_threshold_preserves_last_failure_trace() -> None:
    full_exception_trace = "Traceback...\noriginal group sync failure"

    with pytest.raises(ExternalGroupSyncFailureThresholdError) as exc_info:
        _check_external_group_failure_threshold(
            total_failures=4,
            total_groups_seen=10,
            last_failure=_failure(full_exception_trace=full_exception_trace),
        )

    assert exc_info.value.full_exception_trace == full_exception_trace
