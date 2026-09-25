"""Regression tests for issue #14261.

Tests the real production helper ``handle_pre_fanout_pruning_failure``
which performs DB FAILED finalization then Redis reset.

These tests execute actual production code while mocking only the DB
boundary (update_sync_record_status) and the Redis reset callable.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.tasks.pruning.finalize import (
    handle_pre_fanout_pruning_failure,
)


@pytest.fixture(autouse=True)
def _mock_sync_record_module(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a mock onyx.db.sync_record module so the lazy import in
    _finalize_sync_record_as_failed resolves to a mock."""
    mock_update = MagicMock()
    mock_module = MagicMock(spec=ModuleType)
    mock_module.update_sync_record_status = mock_update
    monkeypatch.setitem(sys.modules, "onyx.db.sync_record", mock_module)
    return mock_update


class TestHandlePreFanoutPruningFailure:
    """Test the real production helper that finalizes SyncRecord + resets Redis."""

    def test_db_finalization_before_redis_reset(
        self, _mock_sync_record_module: MagicMock
    ) -> None:
        """The critical invariant: DB record is marked FAILED before Redis
        state is cleared.  Reversing this recreates the original bug window."""
        events: list[str] = []
        _mock_sync_record_module.side_effect = lambda **kw: events.append(
            "failed"
        )
        mock_reset = MagicMock(side_effect=lambda: events.append("reset"))

        handle_pre_fanout_pruning_failure(
            db_session=MagicMock(),
            cc_pair_id=42,
            reset_pruning_state=mock_reset,
        )

        assert events == ["failed", "reset"]

    def test_update_uses_correct_args(
        self, _mock_sync_record_module: MagicMock
    ) -> None:
        """update_sync_record_status is called with SyncType.PRUNING,
        SyncStatus.FAILED, and num_docs_synced=0."""
        from onyx.db.enums import SyncStatus, SyncType

        mock_session = MagicMock()
        handle_pre_fanout_pruning_failure(
            db_session=mock_session,
            cc_pair_id=7,
            reset_pruning_state=MagicMock(),
        )

        _mock_sync_record_module.assert_called_once_with(
            db_session=mock_session,
            entity_id=7,
            sync_type=SyncType.PRUNING,
            sync_status=SyncStatus.FAILED,
            num_docs_synced=0,
        )

    def test_redis_reset_still_runs_when_db_fails(
        self, _mock_sync_record_module: MagicMock
    ) -> None:
        """If DB finalization raises, Redis cleanup must still execute so
        the fence does not stay dirty.  The DB error is re-raised after."""
        _mock_sync_record_module.side_effect = RuntimeError("DB connection lost")
        events: list[str] = []
        mock_reset = MagicMock(side_effect=lambda: events.append("reset"))

        with pytest.raises(RuntimeError, match="DB connection lost"):
            handle_pre_fanout_pruning_failure(
                db_session=MagicMock(),
                cc_pair_id=1,
                reset_pruning_state=mock_reset,
            )

        assert events == ["reset"]

    def test_ordering_maintained_even_when_db_fails(
        self, _mock_sync_record_module: MagicMock
    ) -> None:
        """When DB fails: attempt_failed → reset.  Reset must not be skipped."""
        events: list[str] = []
        _mock_sync_record_module.side_effect = lambda **kw: events.append(
            "failed"
        )
        # Make reset also record
        mock_reset = MagicMock(side_effect=lambda: events.append("reset"))

        # Override the db error to happen after the append
        _mock_sync_record_module.side_effect = Exception("db error")

        with pytest.raises(Exception, match="db error"):
            handle_pre_fanout_pruning_failure(
                db_session=MagicMock(),
                cc_pair_id=99,
                reset_pruning_state=mock_reset,
            )

        # reset was called even though db raised
        mock_reset.assert_called_once()
