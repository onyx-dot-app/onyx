"""Timing decorators log locally without changing application control flow."""

import asyncio
from collections.abc import Generator
from unittest.mock import Mock

import pytest

from onyx.utils import timing


def test_function_return_and_local_log(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = Mock()
    monkeypatch.setattr(timing.logger, "notice", sink)

    @timing.log_function_time()
    def work(value: int) -> int:
        return value + 1

    assert work(4) == 5
    assert sink.call_count == 1
    assert sink.call_args.args[0].startswith("work took ")


def test_async_function_return(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = Mock()
    monkeypatch.setattr(timing.logger, "notice", sink)

    @timing.log_function_time()
    async def work() -> int:
        return 7

    assert asyncio.run(work()) == 7
    sink.assert_called_once()


def test_generator_close_cleans_up_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = Mock()
    monkeypatch.setattr(timing.logger, "info", sink)
    cleaned = []

    @timing.log_generator_function_time()
    def work() -> Generator[int, None, None]:
        try:
            yield 1
        finally:
            cleaned.append(True)

    result = work()
    assert next(result) == 1
    result.close()
    assert cleaned == [True]
    sink.assert_called_once()


def test_generator_exception_propagates_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = Mock()
    monkeypatch.setattr(timing.logger, "info", sink)

    @timing.log_generator_function_time()
    def work() -> Generator[int, None, None]:
        yield 1
        raise RuntimeError("expected failure")

    result = work()
    assert next(result) == 1
    with pytest.raises(RuntimeError, match="expected failure"):
        next(result)
    sink.assert_called_once()
