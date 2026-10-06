"""Lazy file copies share content without copying storage locks."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

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
    calls = 0

    def load() -> bytes:
        nonlocal calls
        calls += 1
        return b"content"

    original = _file(kind, load)
    copied = original.model_copy(deep=deep)
    assert copied is not original
    assert calls == 0
    assert copied.content == original.content == b"content"
    assert calls == 1
    assert copied.model_dump() == original.model_dump()
    assert copied.model_copy(deep=True).content == b"content"
    assert calls == 1


@pytest.mark.parametrize("kind", ["chat", "memory"])
def test_concurrent_copies_share_one_load(kind: str) -> None:
    calls = 0
    lock = Lock()
    barrier = Barrier(3)

    def load() -> bytes:
        nonlocal calls
        with lock:
            calls += 1
        return b"content"

    original = _file(kind, load)
    files = [original, original.model_copy(), original.model_copy(deep=True)]

    def read(file: InMemoryChatFile | ChatFile) -> bytes:
        barrier.wait(timeout=5)
        return file.content

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(read, files))
    assert results == [b"content"] * 3
    assert calls == 1


@pytest.mark.parametrize("kind", ["chat", "memory"])
def test_serialization_keeps_resource_outside_fields(kind: str) -> None:
    calls = 0

    def load() -> bytes:
        nonlocal calls
        calls += 1
        return b"content"

    original = _file(kind, load)
    copied = original.model_copy(deep=True)
    before = copied.model_dump()
    assert before["content"] == b""
    assert not any(key.startswith("_lazy") for key in before)
    assert copied.model_dump_json() == original.model_dump_json()
    assert calls == 0
    assert copied.content == b"content"
    after = copied.model_dump()
    assert after["content"] == b"content"
    assert not any(key.startswith("_lazy") for key in after)
    assert calls == 1
