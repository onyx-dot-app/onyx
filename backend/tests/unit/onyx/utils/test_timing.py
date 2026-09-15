"""The timing decorators attach a user id to every latency telemetry record."""

import logging
from collections.abc import Generator
from typing import Any
from unittest.mock import Mock

import pytest

from onyx.utils import timing
from onyx.utils.telemetry import RecordType
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR


@pytest.fixture
def telemetry_sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    sink = Mock(return_value=None)
    monkeypatch.setattr(timing, "optional_telemetry", sink)
    return sink


@pytest.fixture
def request_user() -> Generator[str, None, None]:
    token = CURRENT_USER_ID_CONTEXTVAR.set("request-user")
    try:
        yield "request-user"
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)


def _record_user_id(sink: Mock) -> str:
    assert sink.call_count == 1
    kwargs = sink.call_args.kwargs
    assert kwargs["record_type"] == RecordType.LATENCY
    return kwargs["user_id"]


def test_function_record_uses_request_user_without_user_kwarg(
    telemetry_sink: Mock, request_user: str
) -> None:
    @timing.log_function_time()
    def work() -> int:
        return 1

    assert work() == 1
    assert _record_user_id(telemetry_sink) == request_user


@pytest.mark.usefixtures("request_user")
def test_function_record_prefers_explicit_user_kwarg(telemetry_sink: Mock) -> None:
    explicit = Mock()
    explicit.id = "explicit-user"

    @timing.log_function_time()
    def work(user: Any) -> str:
        return str(user.id)

    assert work(user=explicit) == "explicit-user"
    assert _record_user_id(telemetry_sink) == "explicit-user"


def test_function_record_is_unknown_outside_a_request(telemetry_sink: Mock) -> None:
    @timing.log_function_time()
    def work() -> int:
        return 1

    assert work() == 1
    assert _record_user_id(telemetry_sink) == "Unknown"


def test_function_record_is_unknown_when_user_has_no_id(
    telemetry_sink: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    @timing.log_function_time()
    def work(user: Any) -> int:
        return len(user)

    with caplog.at_level(logging.WARNING):
        assert work(user="not a user object") == 17

    assert _record_user_id(telemetry_sink) == "Unknown"
    assert "Failed to resolve user id for latency telemetry" in caplog.text


def test_generator_record_uses_request_user_without_user_kwarg(
    telemetry_sink: Mock, request_user: str
) -> None:
    @timing.log_generator_function_time()
    def work() -> Generator[int, None, None]:
        yield 1
        yield 2

    assert list(work()) == [1, 2]
    assert _record_user_id(telemetry_sink) == request_user
