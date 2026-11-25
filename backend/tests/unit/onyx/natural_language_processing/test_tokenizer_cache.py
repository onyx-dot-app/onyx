"""Threads that miss the tokenizer cache together load the tokenizer once."""

import threading
from unittest.mock import MagicMock

import pytest

from onyx.natural_language_processing import utils
from onyx.natural_language_processing.utils import BaseTokenizer

_MODEL = "test/model"
_TIMEOUT_S = 10


class _SpyLock:
    """A lock that counts the threads that asked for it."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.requests = threading.Semaphore(0)

    def __enter__(self) -> None:
        self.requests.release()
        self._lock.acquire()

    def __exit__(self, *_exc: object) -> None:
        self._lock.release()


def test_concurrent_cache_misses_load_one_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_started = threading.Event()
    finish_load = threading.Event()
    loads: list[str] = []

    def slow_load(model_name: str) -> BaseTokenizer:
        loads.append(model_name)
        load_started.set()
        finish_load.wait(_TIMEOUT_S)
        return MagicMock(spec=BaseTokenizer)

    spy_lock = _SpyLock()
    monkeypatch.setattr(utils, "_TOKENIZER_CACHE", {})
    monkeypatch.setattr(utils, "_TOKENIZER_LOAD_LOCK", spy_lock)
    monkeypatch.setattr(utils, "HuggingFaceTokenizer", slow_load)

    results: list[BaseTokenizer] = []

    def load() -> None:
        results.append(utils.get_tokenizer(model_name=_MODEL, provider_type=None))

    first = threading.Thread(target=load)
    second = threading.Thread(target=load)
    started: list[threading.Thread] = []
    try:
        first.start()
        started.append(first)
        assert load_started.wait(_TIMEOUT_S)
        second.start()
        started.append(second)
        # The second thread must wait for the lock while the first one loads.
        assert spy_lock.requests.acquire(timeout=_TIMEOUT_S)
        assert spy_lock.requests.acquire(timeout=_TIMEOUT_S)
    finally:
        # No thread may run after the fixture puts the globals back.
        finish_load.set()
        for thread in started:
            thread.join(_TIMEOUT_S)

    assert loads == [_MODEL]
    assert len(results) == 2
    assert results[0] is results[1]
