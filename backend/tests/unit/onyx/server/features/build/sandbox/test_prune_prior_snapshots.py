"""Unit tests for prune-on-write: deleting a session's superseded snapshots."""

from unittest.mock import MagicMock
from uuid import uuid4

from onyx.background.celery.tasks.build.tasks import _prune_prior_session_snapshots
from onyx.db.models import Snapshot


def _snap() -> Snapshot:
    sid = uuid4()
    return Snapshot(
        id=sid, session_id=uuid4(), storage_path=f"snap/{sid}.tar.gz", size_bytes=1
    )


def test_prunes_blob_then_row_for_each_prior() -> None:
    db_session = MagicMock()
    snapshot_manager = MagicMock()
    priors = [_snap(), _snap(), _snap()]

    _prune_prior_session_snapshots(db_session, snapshot_manager, priors)

    assert snapshot_manager.delete_snapshot.call_count == 3
    snapshot_manager.delete_snapshot.assert_any_call(priors[0].storage_path)
    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == priors


def test_empty_priors_is_a_noop() -> None:
    db_session = MagicMock()
    snapshot_manager = MagicMock()

    _prune_prior_session_snapshots(db_session, snapshot_manager, [])

    snapshot_manager.delete_snapshot.assert_not_called()
    db_session.delete.assert_not_called()


def test_blob_delete_failure_keeps_that_row_but_continues() -> None:
    db_session = MagicMock()
    snapshot_manager = MagicMock()
    priors = [_snap(), _snap(), _snap()]
    # Second blob delete fails; its row must be kept, the rest still pruned.
    snapshot_manager.delete_snapshot.side_effect = [None, RuntimeError("s3 down"), None]

    _prune_prior_session_snapshots(db_session, snapshot_manager, priors)

    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == [priors[0], priors[2]]
    assert priors[1] not in deleted_rows
