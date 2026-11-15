"""External dependency unit tests for the async log-export start endpoint.

Runs against the real (Postgres/MinIO-backed) file store; celery sends and log
directories are patched.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.log_export import api as log_export_api
from ee.onyx.server.log_export.api import (
    API_SERVER_WORKER_NAME,
    _ExpiringLock,
    get_log_export_status,
    start_log_export,
)
from ee.onyx.server.log_export.models import LogExportState
from ee.onyx.server.log_export.storage import (
    LOG_EXPORT_COLLECTION_DEADLINE,
    derive_export_state,
    read_export_snapshot,
)
from onyx.cache.interface import CacheBackendType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

pytestmark = pytest.mark.usefixtures(
    "db_session", "tenant_context", "initialize_file_store"
)

_API_MODULE = "ee.onyx.server.log_export.api"


@pytest.fixture(autouse=True)
def _fresh_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gives each test its own export lock; the real one holds for 90s."""
    monkeypatch.setattr(
        log_export_api,
        "_ASYNC_EXPORT_LOCK",
        _ExpiringLock(ttl_seconds=LOG_EXPORT_COLLECTION_DEADLINE.total_seconds()),
    )
    # Token numbering restarts with each fresh lock, so a pair leaked by an
    # earlier test could otherwise release this test's hold.
    monkeypatch.setattr(log_export_api, "_ACTIVE_EXPORT", None)


@pytest.fixture(autouse=True)
def _tmp_log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "onyx_debug.log").write_text("a log line\n")
    monkeypatch.setattr(
        log_export_api, "get_default_log_directories", lambda: [tmp_path]
    )


def _admin_user() -> MagicMock:
    user = MagicMock()
    user.email = "admin@example.com"
    return user


def test_fanout_failure_degrades_to_api_server_only() -> None:
    # Precondition.
    # A broker is configured but unreachable.
    with patch(f"{_API_MODULE}.client_app") as celery_client:
        celery_client.send_task.side_effect = OSError("broker down")

        # Under test.
        response = start_log_export(user=_admin_user())

    # Postcondition.
    # The manifest awaits only the api_server, whose inline receipt already
    # exists, so the export is ready without any deadline wait.
    snapshot = read_export_snapshot(response.export_id)
    assert snapshot is not None
    assert snapshot.manifest.worker_names == [API_SERVER_WORKER_NAME]
    now = datetime.now(tz=timezone.utc)
    assert derive_export_state(snapshot, now=now) is LogExportState.READY


def test_lite_deployment_skips_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Precondition.
    # Redis is absent by design (the onyx-lite overlay), so there is no celery
    # broker and there are no workers.
    monkeypatch.setattr(log_export_api, "CACHE_BACKEND", CacheBackendType.POSTGRES)
    with patch(f"{_API_MODULE}.client_app") as celery_client:
        # Under test.
        response = start_log_export(user=_admin_user())

    # Postcondition.
    # The broker is never touched, and the manifest awaits only the api_server,
    # whose inline receipt already exists.
    celery_client.send_task.assert_not_called()
    snapshot = read_export_snapshot(response.export_id)
    assert snapshot is not None
    assert snapshot.manifest.worker_names == [API_SERVER_WORKER_NAME]
    now = datetime.now(tz=timezone.utc)
    assert derive_export_state(snapshot, now=now) is LogExportState.READY


def test_failed_start_releases_lock() -> None:
    # Precondition.
    with (
        patch(f"{_API_MODULE}.client_app"),
        patch(f"{_API_MODULE}.save_manifest", side_effect=OSError("store down")),
    ):
        # Under test.
        with pytest.raises(OSError):
            start_log_export(user=_admin_user())

    # Postcondition.
    # A retry is not rate-limited by the failed attempt.
    assert not log_export_api._ASYNC_EXPORT_LOCK.held()


def test_ready_status_poll_frees_the_export_slot() -> None:
    # Precondition.
    # A degraded start awaiting only the api_server, whose inline receipt
    # already exists, so the first status poll observes ready.
    with patch(f"{_API_MODULE}.client_app") as celery_client:
        celery_client.send_task.side_effect = OSError("no broker")
        response = start_log_export(user=_admin_user())
    assert log_export_api._ASYNC_EXPORT_LOCK.held()

    # Under test.
    status = get_log_export_status(response.export_id)

    # Postcondition.
    # The slot is free and a new export can start at once.
    assert status.state is LogExportState.READY
    assert not log_export_api._ASYNC_EXPORT_LOCK.held()
    with patch(f"{_API_MODULE}.client_app"):
        start_log_export(user=_admin_user())


def test_successful_start_holds_lock_for_collection_window() -> None:
    # Precondition.
    with patch(f"{_API_MODULE}.client_app"):
        start_log_export(user=_admin_user())

        # Under test and postcondition.
        with pytest.raises(OnyxError) as exc_info:
            start_log_export(user=_admin_user())
        assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
