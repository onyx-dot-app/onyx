"""Unit tests for prune-on-write: deleting a session's superseded snapshots."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.models import Snapshot
from onyx.server.features.build.session import sandbox_lifecycle
from onyx.server.features.build.session.sandbox_lifecycle import (
    persist_session_snapshot_keep_latest,
)


def _snap() -> Snapshot:
    sid = uuid4()
    return Snapshot(
        id=sid, session_id=uuid4(), storage_path=f"snap/{sid}.tar.gz", size_bytes=1
    )


def _db_session_with_priors(priors: list[Snapshot]) -> MagicMock:
    db_session = MagicMock()
    db_session.execute.return_value.scalars.return_value.all.return_value = priors
    return db_session


def _stub_snapshot_manager(
    monkeypatch: pytest.MonkeyPatch, snapshot_manager: MagicMock
) -> None:
    monkeypatch.setattr(sandbox_lifecycle, "get_default_file_store", lambda: object())
    monkeypatch.setattr(
        sandbox_lifecycle, "SnapshotManager", lambda _file_store: snapshot_manager
    )


def test_prunes_blob_then_row_for_each_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    priors = [_snap(), _snap(), _snap()]
    db_session = _db_session_with_priors(priors)
    snapshot_manager = MagicMock()
    _stub_snapshot_manager(monkeypatch, snapshot_manager)

    snapshot = persist_session_snapshot_keep_latest(
        db_session=db_session,
        session_id=session_id,
        storage_path="snap/new.tar.gz",
        size_bytes=123,
    )

    assert snapshot.session_id == session_id
    assert snapshot.storage_path == "snap/new.tar.gz"
    assert snapshot.size_bytes == 123
    db_session.add.assert_called_once_with(snapshot)
    db_session.commit.assert_called_once()
    assert snapshot_manager.delete_snapshot.call_count == 3
    snapshot_manager.delete_snapshot.assert_any_call(priors[0].storage_path)
    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == priors


def test_empty_priors_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    db_session = _db_session_with_priors([])
    snapshot_manager = MagicMock()
    _stub_snapshot_manager(monkeypatch, snapshot_manager)

    persist_session_snapshot_keep_latest(
        db_session=db_session,
        session_id=uuid4(),
        storage_path="snap/new.tar.gz",
        size_bytes=123,
    )

    snapshot_manager.delete_snapshot.assert_not_called()
    db_session.delete.assert_not_called()
    db_session.commit.assert_called_once()


def test_blob_delete_failure_keeps_that_row_but_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    priors = [_snap(), _snap(), _snap()]
    db_session = _db_session_with_priors(priors)
    snapshot_manager = MagicMock()
    _stub_snapshot_manager(monkeypatch, snapshot_manager)
    # Second blob delete fails; its row must be kept, the rest still pruned.
    snapshot_manager.delete_snapshot.side_effect = [None, RuntimeError("s3 down"), None]

    persist_session_snapshot_keep_latest(
        db_session=db_session,
        session_id=uuid4(),
        storage_path="snap/new.tar.gz",
        size_bytes=123,
    )

    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == [priors[0], priors[2]]
    assert priors[1] not in deleted_rows
    db_session.commit.assert_called_once()
