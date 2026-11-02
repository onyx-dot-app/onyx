"""Lazy file copies share content without copying storage locks."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.file_store.models import ChatFileType, InMemoryChatFile
from onyx.tools.models import ChatFile


def _file(kind: str, loader: Callable[[], bytes]) -> InMemoryChatFile | ChatFile:
    if kind == "chat":
        return ChatFile.lazy_from_filename(filename="source.txt", loader=loader)
    return InMemoryChatFile.lazy_from_descriptor(
        file_id="source",
        file_type=ChatFileType.PLAIN_TEXT,
        filename="source.txt",
        loader=loader,
    )


@pytest.mark.parametrize("kind", ["chat", "memory"])
@pytest.mark.parametrize("deep", [False, True])
def test_copies_share_one_load(kind: str, deep: bool) -> None:
    calls: int = 0

    def load() -> bytes:
        nonlocal calls
        calls += 1
        return b"content"

    original: InMemoryChatFile | ChatFile = _file(kind, load)
    copied: InMemoryChatFile | ChatFile = original.model_copy(deep=deep)
    assert copied is not original
    assert calls == 0
    assert copied.content == original.content == b"content"
    assert calls == 1
    assert copied.model_dump() == original.model_dump()
    assert copied.model_copy(deep=True).content == b"content"
    assert calls == 1


@pytest.mark.parametrize("kind", ["chat", "memory"])
def test_concurrent_copies_share_one_load(kind: str) -> None:
    calls: int = 0
    attempts: int = 0
    counter_lock: Lock = Lock()
    content_lock: Lock = Lock()
    loader_started: Event = Event()
    all_readers_started: Event = Event()
    release_loader: Event = Event()
    tracked_lock: MagicMock = MagicMock()

    def acquire() -> None:
        nonlocal attempts
        with counter_lock:
            attempts += 1
            if attempts == 3:
                all_readers_started.set()
        content_lock.acquire()

    def release(*_args: object) -> None:
        content_lock.release()

    tracked_lock.__enter__.side_effect = acquire
    tracked_lock.__exit__.side_effect = release

    def load() -> bytes:
        nonlocal calls
        with counter_lock:
            calls += 1
        loader_started.set()
        assert release_loader.wait(timeout=5)
        return b"content"

    with patch("onyx.file_store.models.threading.Lock", return_value=tracked_lock):
        original: InMemoryChatFile | ChatFile = _file(kind, load)
    files: list[InMemoryChatFile | ChatFile] = [
        original,
        original.model_copy(),
        original.model_copy(deep=True),
    ]

    def read(file: InMemoryChatFile | ChatFile) -> bytes:
        return file.content

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures: list[Future[bytes]] = [executor.submit(read, file) for file in files]
        try:
            assert loader_started.wait(timeout=5)
            assert all_readers_started.wait(timeout=5)
            assert calls == 1
        finally:
            release_loader.set()
        results: list[bytes] = [future.result(timeout=5) for future in futures]
    assert results == [b"content"] * 3
    assert calls == 1


@pytest.mark.parametrize("kind", ["chat", "memory"])
def test_serialization_keeps_resource_outside_fields(kind: str) -> None:
    calls: int = 0

    def load() -> bytes:
        nonlocal calls
        calls += 1
        return b"content"

    original: InMemoryChatFile | ChatFile = _file(kind, load)
    copied: InMemoryChatFile | ChatFile = original.model_copy(deep=True)
    before: dict[str, Any] = copied.model_dump()
    assert before["content"] == b""
    assert not any(key.startswith("_lazy") for key in before)
    assert copied.model_dump_json() == original.model_dump_json()
    assert calls == 0
    assert copied.content == b"content"
    after: dict[str, Any] = copied.model_dump()
    assert after["content"] == b"content"
    assert not any(key.startswith("_lazy") for key in after)
    assert calls == 1
