import pytest

from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    _check_external_group_failure_threshold,
)
from ee.onyx.db.external_perm import ExternalGroupSyncFailure


def _failure() -> ExternalGroupSyncFailure:
    return ExternalGroupSyncFailure(
        external_group_id="group-id",
        external_group_name="group-name",
        failure_message="group sync failed",
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
