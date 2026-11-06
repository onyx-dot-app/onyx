"""The export start awaits a ``kubernetes`` receipt and starts its collector off
the request path only when the Kubernetes collection is enabled."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from ee.onyx.server.log_export import api as log_export_api
from ee.onyx.server.log_export.api import (
    API_SERVER_WORKER_NAME,
    _ExpiringLock,
    start_log_export,
)
from ee.onyx.server.log_export.kubernetes_collection import KUBERNETES_WORKER_NAME
from ee.onyx.server.log_export.models import LogExportManifest
from ee.onyx.server.log_export.storage import LOG_EXPORT_COLLECTION_DEADLINE
from onyx.cache.interface import CacheBackendType


class _StartedThread:
    def __init__(self, target: Callable[..., None], kwargs: dict[str, Any]) -> None:
        self.target = target
        self.kwargs = kwargs


@pytest.fixture
def saved_manifests(monkeypatch: pytest.MonkeyPatch) -> list[LogExportManifest]:
    manifests: list[LogExportManifest] = []
    monkeypatch.setattr(
        log_export_api,
        "_ASYNC_EXPORT_LOCK",
        _ExpiringLock(ttl_seconds=LOG_EXPORT_COLLECTION_DEADLINE.total_seconds()),
    )
    monkeypatch.setattr(log_export_api, "_ACTIVE_EXPORT", None)
    # No broker, so only the api_server and Kubernetes collectors are awaited.
    monkeypatch.setattr(log_export_api, "CACHE_BACKEND", CacheBackendType.POSTGRES)
    monkeypatch.setattr(log_export_api, "save_manifest", manifests.append)
    monkeypatch.setattr(log_export_api, "collect_logs_into_file_store", MagicMock())
    return manifests


@pytest.fixture
def started_threads(monkeypatch: pytest.MonkeyPatch) -> list[_StartedThread]:
    threads: list[_StartedThread] = []

    def _start(target: Callable[..., None], **kwargs: Any) -> None:
        threads.append(_StartedThread(target, kwargs["kwargs"]))

    monkeypatch.setattr(log_export_api, "start_thread_with_context", _start)
    return threads


def _admin_user() -> MagicMock:
    user = MagicMock()
    user.email = "admin@example.com"
    return user


def test_kubernetes_collection_is_awaited_and_started(
    monkeypatch: pytest.MonkeyPatch,
    saved_manifests: list[LogExportManifest],
    started_threads: list[_StartedThread],
) -> None:
    # Precondition.
    monkeypatch.setattr(log_export_api, "KUBERNETES_COLLECTION_ENABLED", True)

    # Under test.
    response = start_log_export(user=_admin_user())

    # Postcondition.
    # The manifest waits for the Kubernetes receipt, and the collector runs in
    # the background for this export until its deadline.
    [manifest] = saved_manifests
    assert manifest.worker_names == [API_SERVER_WORKER_NAME, KUBERNETES_WORKER_NAME]
    [thread] = started_threads
    assert thread.kwargs == {
        "export_id": response.export_id,
        "deadline": manifest.deadline,
    }


def test_kubernetes_collection_disabled(
    monkeypatch: pytest.MonkeyPatch,
    saved_manifests: list[LogExportManifest],
    started_threads: list[_StartedThread],
) -> None:
    # Precondition.
    monkeypatch.setattr(log_export_api, "KUBERNETES_COLLECTION_ENABLED", False)

    # Under test.
    start_log_export(user=_admin_user())

    # Postcondition.
    [manifest] = saved_manifests
    assert manifest.worker_names == [API_SERVER_WORKER_NAME]
    assert started_threads == []
