"""Unit tests for prune-on-write: deleting a session's superseded snapshots."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.models import Snapshot
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.session import sandbox_lifecycle
from onyx.server.features.build.session.sandbox_lifecycle import (
    create_session_snapshot_keep_latest,
)


def _snap() -> Snapshot:
    sid = uuid4()
    return Snapshot(
        id=sid, session_id=uuid4(), storage_path=f"snap/{sid}.tar.gz", size_bytes=1
    )


def _stub_snapshot_manager(
    monkeypatch: pytest.MonkeyPatch, snapshot_manager: MagicMock
) -> None:
    monkeypatch.setattr(sandbox_lifecycle, "get_default_file_store", lambda: object())
    monkeypatch.setattr(
        sandbox_lifecycle, "SnapshotManager", lambda _file_store: snapshot_manager
    )


def _stub_prior_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    db_session: MagicMock,
    session_id: object,
    priors: list[Snapshot],
) -> None:
    def _get_snapshots_for_session(
        _db_session: MagicMock, requested_session_id: object
    ) -> list[Snapshot]:
        assert _db_session is db_session
        assert requested_session_id == session_id
        return priors

    monkeypatch.setattr(
        sandbox_lifecycle, "get_snapshots_for_session", _get_snapshots_for_session
    )


def test_prunes_blob_then_row_for_each_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    sandbox_id = uuid4()
    priors = [_snap(), _snap(), _snap()]
    db_session = MagicMock()
    sandbox_manager = MagicMock()
    sandbox_manager.create_snapshot.return_value = SnapshotResult(
        storage_path="snap/new.tar.gz", size_bytes=123
    )
    snapshot_manager = MagicMock()
    _stub_prior_snapshots(monkeypatch, db_session, session_id, priors)
    _stub_snapshot_manager(monkeypatch, snapshot_manager)

    result = create_session_snapshot_keep_latest(
        sandbox_manager=sandbox_manager,
        db_session=db_session,
        sandbox_id=sandbox_id,
        session_id=session_id,
        tenant_id="tenant-a",
    )

    assert result == SnapshotResult(storage_path="snap/new.tar.gz", size_bytes=123)
    created_snapshot = db_session.add.call_args.args[0]
    assert created_snapshot.session_id == session_id
    assert created_snapshot.storage_path == "snap/new.tar.gz"
    assert created_snapshot.size_bytes == 123
    db_session.commit.assert_called_once()
    assert snapshot_manager.delete_snapshot.call_count == 3
    snapshot_manager.delete_snapshot.assert_any_call(priors[0].storage_path)
    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == priors


def test_empty_priors_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    db_session = MagicMock()
    sandbox_manager = MagicMock()
    sandbox_manager.create_snapshot.return_value = SnapshotResult(
        storage_path="snap/new.tar.gz", size_bytes=123
    )
    snapshot_manager = MagicMock()
    _stub_prior_snapshots(monkeypatch, db_session, session_id, [])
    _stub_snapshot_manager(monkeypatch, snapshot_manager)

    create_session_snapshot_keep_latest(
        sandbox_manager=sandbox_manager,
        db_session=db_session,
        sandbox_id=uuid4(),
        session_id=session_id,
        tenant_id="tenant-a",
    )

    snapshot_manager.delete_snapshot.assert_not_called()
    db_session.delete.assert_not_called()
    db_session.commit.assert_called_once()


def test_blob_delete_failure_keeps_that_row_but_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    priors = [_snap(), _snap(), _snap()]
    db_session = MagicMock()
    sandbox_manager = MagicMock()
    sandbox_manager.create_snapshot.return_value = SnapshotResult(
        storage_path="snap/new.tar.gz", size_bytes=123
    )
    snapshot_manager = MagicMock()
    _stub_prior_snapshots(monkeypatch, db_session, session_id, priors)
    _stub_snapshot_manager(monkeypatch, snapshot_manager)
    # Second blob delete fails; its row must be kept, the rest still pruned.
    snapshot_manager.delete_snapshot.side_effect = [None, RuntimeError("s3 down"), None]

    create_session_snapshot_keep_latest(
        sandbox_manager=sandbox_manager,
        db_session=db_session,
        sandbox_id=uuid4(),
        session_id=session_id,
        tenant_id="tenant-a",
    )

    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == [priors[0], priors[2]]
    assert priors[1] not in deleted_rows
    db_session.commit.assert_called_once()


def test_create_snapshot_does_not_prune_snapshots_created_during_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session = MagicMock()
    sandbox_manager = MagicMock()
    sandbox_id = uuid4()
    session_id = uuid4()
    old_snapshot = _snap()
    concurrent_snapshot = _snap()
    visible_snapshots = [old_snapshot]
    snapshot_manager = MagicMock()
    _stub_snapshot_manager(monkeypatch, snapshot_manager)

    def _get_snapshots_for_session(
        _db_session: MagicMock, requested_session_id: object
    ) -> list[Snapshot]:
        assert _db_session is db_session
        assert requested_session_id == session_id
        return list(visible_snapshots)

    def _create_snapshot(**kwargs: object) -> SnapshotResult:
        assert kwargs == {
            "sandbox_id": sandbox_id,
            "session_id": session_id,
            "tenant_id": "tenant-a",
        }
        visible_snapshots.append(concurrent_snapshot)
        return SnapshotResult(storage_path="snap/new.tar.gz", size_bytes=123)

    monkeypatch.setattr(
        sandbox_lifecycle, "get_snapshots_for_session", _get_snapshots_for_session
    )
    monkeypatch.setattr(sandbox_manager, "create_snapshot", _create_snapshot)

    result = create_session_snapshot_keep_latest(
        sandbox_manager=sandbox_manager,
        db_session=db_session,
        sandbox_id=sandbox_id,
        session_id=session_id,
        tenant_id="tenant-a",
    )

    assert result is not None
    assert result.storage_path == "snap/new.tar.gz"
    assert result.size_bytes == 123
    deleted_rows = [c.args[0] for c in db_session.delete.call_args_list]
    assert deleted_rows == [old_snapshot]
    assert concurrent_snapshot not in deleted_rows
