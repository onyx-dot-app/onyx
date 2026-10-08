"""The default file store is built once per process. Every image and
attachment a connector stores went through a fresh store, and so a fresh S3
client, before; the client is the expensive part."""

import threading
from unittest.mock import MagicMock, patch

from onyx.file_store import file_store as file_store_module
from onyx.file_store.file_store import FileStore, get_default_file_store


def test_the_default_file_store_is_built_once() -> None:
    with (
        patch.object(file_store_module, "_DEFAULT_FILE_STORE", None),
        patch.object(file_store_module, "_build_default_file_store") as build,
    ):
        first: FileStore = get_default_file_store()
        second: FileStore = get_default_file_store()

    assert first is second
    assert build.call_count == 1


def test_overlapping_first_calls_build_one_store() -> None:
    """Two threads asking before the store exists must wait on one build, or
    each would hold a different store."""
    started: threading.Event = threading.Event()
    second_asked: threading.Event = threading.Event()
    release: threading.Event = threading.Event()
    store: FileStore = MagicMock(spec=FileStore)
    stores: list[FileStore] = []

    def slow_build() -> FileStore:
        started.set()
        release.wait(timeout=5)
        return store

    def ask_second() -> None:
        second_asked.set()
        stores.append(get_default_file_store())

    with (
        patch.object(file_store_module, "_DEFAULT_FILE_STORE", None),
        patch.object(
            file_store_module, "_build_default_file_store", side_effect=slow_build
        ) as build,
    ):
        first: threading.Thread = threading.Thread(
            target=lambda: stores.append(get_default_file_store())
        )
        second: threading.Thread = threading.Thread(target=ask_second)
        first.start()
        assert started.wait(timeout=5)
        second.start()
        assert second_asked.wait(timeout=5)
        # The first build is still held open, so the second caller must be
        # parked behind it rather than building a store of its own.
        second.join(timeout=0.5)
        assert second.is_alive()
        assert build.call_count == 1
        release.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert stores == [store, store]
    assert build.call_count == 1
