"""Unit coverage for on-demand build-session snapshot endpoints."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.session import api as session_api


def _mock_owned_sandbox(monkeypatch: pytest.MonkeyPatch, sandbox_id: object) -> None:
    monkeypatch.setattr(
        session_api,
        "_owned_session_sandbox",
        lambda *_args, **_kwargs: cast(Sandbox, SimpleNamespace(id=sandbox_id)),
    )


def test_create_session_snapshot_persists_and_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    sandbox_id = uuid4()
    user = cast(User, SimpleNamespace(id=uuid4()))
    db_session = cast(Session, MagicMock())
    sandbox_manager = MagicMock()
    create_snapshot = MagicMock(
        return_value=SnapshotResult(
            storage_path="snapshots/session.tar.gz",
            size_bytes=123,
        )
    )

    _mock_owned_sandbox(monkeypatch, sandbox_id)
    monkeypatch.setattr(session_api, "get_sandbox_manager", lambda: sandbox_manager)
    monkeypatch.setattr(session_api, "get_current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(
        session_api,
        "create_session_snapshot_keep_latest",
        create_snapshot,
    )

    response = session_api.create_session_snapshot(
        session_id=session_id,
        user=user,
        db_session=db_session,
    )

    assert response.status_code == 200
    assert json.loads(bytes(response.body)) == {
        "storage_path": "snapshots/session.tar.gz",
        "size_bytes": 123,
    }
    create_snapshot.assert_called_once_with(
        sandbox_manager=sandbox_manager,
        db_session=db_session,
        sandbox_id=sandbox_id,
        session_id=session_id,
        tenant_id="tenant-a",
    )


def test_create_session_snapshot_maps_runtime_failure_to_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_manager = MagicMock()
    create_snapshot = MagicMock(side_effect=RuntimeError("sidecar unavailable"))

    _mock_owned_sandbox(monkeypatch, uuid4())
    monkeypatch.setattr(session_api, "get_sandbox_manager", lambda: sandbox_manager)
    monkeypatch.setattr(session_api, "get_current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(
        session_api,
        "create_session_snapshot_keep_latest",
        create_snapshot,
    )

    with pytest.raises(OnyxError) as exc_info:
        session_api.create_session_snapshot(
            session_id=uuid4(),
            user=cast(User, SimpleNamespace(id=uuid4())),
            db_session=cast(Session, MagicMock()),
        )

    assert exc_info.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    assert exc_info.value.status_code == 503


def test_create_opencode_history_snapshot_maps_runtime_failure_to_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox_manager = MagicMock()
    sandbox_manager.supports_opencode_history_persistence = True
    sandbox_manager.create_opencode_history_snapshot.side_effect = RuntimeError(
        "file store unavailable"
    )

    _mock_owned_sandbox(monkeypatch, uuid4())
    monkeypatch.setattr(session_api, "get_sandbox_manager", lambda: sandbox_manager)
    monkeypatch.setattr(session_api, "get_current_tenant_id", lambda: "tenant-a")

    with pytest.raises(OnyxError) as exc_info:
        session_api.create_session_opencode_history_snapshot(
            session_id=uuid4(),
            user=cast(User, SimpleNamespace(id=uuid4())),
            db_session=cast(Session, MagicMock()),
        )

    assert exc_info.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    assert exc_info.value.status_code == 503
