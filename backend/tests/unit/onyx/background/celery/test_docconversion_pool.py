"""The docconversion worker's Postgres pool holds a connection for each
file thread of each task, for the source with the most file threads."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from onyx.background.celery.apps import docconversion


@pytest.mark.parametrize("concurrency", [1, 2, 6])
@pytest.mark.parametrize(("drive_threads", "sharepoint_threads"), [(32, 16), (8, 48)])
def test_pool_holds_each_conversion_thread(
    concurrency: int,
    drive_threads: int,
    sharepoint_threads: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docconversion, "GOOGLE_DRIVE_CONVERSION_WORKERS", drive_threads)
    monkeypatch.setattr(
        docconversion, "SHAREPOINT_CONVERSION_WORKERS", sharepoint_threads
    )
    init_kwargs: dict[str, Any] = {}

    def init_engine(**kwargs: Any) -> None:
        init_kwargs.update(kwargs)

    with (
        patch.object(docconversion.SqlEngine, "set_app_name"),
        patch.object(docconversion.SqlEngine, "init_engine", init_engine),
        patch.object(docconversion.app_base, "wait_for_redis"),
        patch.object(docconversion.app_base, "wait_for_db"),
        patch.object(docconversion.app_base, "on_secondary_worker_init"),
    ):
        docconversion.on_worker_init(
            sender=SimpleNamespace(concurrency=concurrency)  # ty: ignore[invalid-argument-type]
        )

    # A task thread and its file threads, for each task.
    file_threads = max(drive_threads, sharepoint_threads)
    assert init_kwargs["pool_size"] >= concurrency * (file_threads + 1)
