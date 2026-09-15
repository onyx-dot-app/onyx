"""Verify every path through the send-message endpoint emits a ``latency`` record.

``handle_send_chat_message`` fans out to three flows: single-model streaming,
multi-model streaming, and the non-streaming API. Each flow ends in a generator
decorated with ``log_generator_function_time``. These tests call the endpoint
directly with the LLM turn stubbed out and assert the telemetry record for each
flow, plus the failure and client-disconnect exits.
"""

import asyncio
from collections.abc import Generator, Mapping
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse

from onyx.chat import process_message
from onyx.chat.models import AnswerStream, ChatFullResponse
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.utils import timing
from onyx.utils.telemetry import RecordType
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR

_USER_ID = "3f1c9a7e-0f38-4c3d-9a55-2d9e8a1b4c6d"


def _packet() -> MessageResponseIDInfo:
    return MessageResponseIDInfo(user_message_id=1, reserved_assistant_message_id=2)


def _mock_user() -> Mock:
    user = Mock()
    user.id = _USER_ID
    user.is_anonymous = False
    return user


def _request() -> Request:
    # A bare request with no Authorization header, so the endpoint treats the
    # caller as a web UI user rather than an API key or PAT client.
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/chat/send-message",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.fixture(autouse=True)
def request_user_context() -> Generator[None, None, None]:
    # The auth dependency sets this for every API request. The timing decorator
    # reads it for functions that have no ``user`` argument.
    token = CURRENT_USER_ID_CONTEXTVAR.set(_USER_ID)
    try:
        yield
    finally:
        CURRENT_USER_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def telemetry_sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    # The decorator resolves ``optional_telemetry`` from the timing module's
    # namespace, so patch it there rather than in ``onyx.utils.telemetry``.
    sink = Mock(return_value=None)
    monkeypatch.setattr(timing, "optional_telemetry", sink)
    return sink


def _install_turn(monkeypatch: pytest.MonkeyPatch, turn: Any) -> None:
    # Both streaming entry points delegate to ``_stream_chat_turn``.
    monkeypatch.setattr(process_message, "_stream_chat_turn", turn)


def _two_packet_turn(**_: Any) -> AnswerStream:
    yield _packet()
    yield _packet()


def _call_endpoint(
    chat_message_req: SendMessageRequest,
) -> StreamingResponse | ChatFullResponse:
    return chat_backend.handle_send_chat_message(
        chat_message_req=chat_message_req,
        request=_request(),
        user=_mock_user(),
        _rate_limit_check=None,
        _api_key_usage_check=None,
    )


def _drain(response: StreamingResponse) -> list[str]:
    """Consume the SSE body the way Starlette would when serving the response."""

    async def collect() -> list[str]:
        return [
            chunk if isinstance(chunk, str) else bytes(chunk).decode()
            async for chunk in response.body_iterator
        ]

    return asyncio.run(collect())


def _latency_records_by_function(sink: Mock) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    for call in sink.call_args_list:
        kwargs = call.kwargs
        assert kwargs["record_type"] == RecordType.LATENCY
        assert kwargs["user_id"] == _USER_ID
        float(kwargs["data"]["latency"])  # stringified seconds, must parse
        records[kwargs["data"]["function"]] = kwargs
    return records


def test_single_model_stream_emits_latency_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(SendMessageRequest(message="hello"))

    # The endpoint returns before the turn runs, so nothing is sent yet.
    assert isinstance(response, StreamingResponse)
    telemetry_sink.assert_not_called()

    chunks = _drain(response)

    assert len(chunks) == 2
    assert set(_latency_records_by_function(telemetry_sink)) == {
        "handle_stream_message_objects"
    }


def test_multi_model_stream_emits_latency_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(
        SendMessageRequest(
            message="hello",
            llm_overrides=[LLMOverride(), LLMOverride()],
        )
    )

    assert isinstance(response, StreamingResponse)
    telemetry_sink.assert_not_called()

    chunks = _drain(response)

    assert len(chunks) == 2
    assert set(_latency_records_by_function(telemetry_sink)) == {
        "handle_multi_model_stream"
    }


def test_non_streaming_emits_latency_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(SendMessageRequest(message="hello", stream=False))

    assert isinstance(response, ChatFullResponse)
    assert response.message_id == 2
    # The turn record plus the aggregation record. ``gather_stream_full`` has no
    # ``user`` argument, so its user id comes from the request contextvar.
    assert set(_latency_records_by_function(telemetry_sink)) == {
        "handle_stream_message_objects",
        "gather_stream_full",
    }


def test_stream_failure_still_emits_latency_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    def failing_turn(**_: Any) -> AnswerStream:
        yield _packet()
        raise RuntimeError("llm exploded")

    _install_turn(monkeypatch, failing_turn)

    response = _call_endpoint(SendMessageRequest(message="hello"))
    assert isinstance(response, StreamingResponse)

    chunks = _drain(response)

    # The endpoint swallows the error into a final JSON line for the client.
    assert len(chunks) == 2
    assert "llm exploded" in chunks[-1]
    assert set(_latency_records_by_function(telemetry_sink)) == {
        "handle_stream_message_objects"
    }


def test_client_disconnect_still_emits_latency_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    # Starlette closes the underlying sync generator when the client goes away.
    # That close is not reachable through ``StreamingResponse`` in a unit test,
    # so drive the decorated generator directly.
    def endless_turn(**_: Any) -> Generator[MessageResponseIDInfo, None, None]:
        while True:
            yield _packet()

    _install_turn(monkeypatch, endless_turn)

    stream = cast(
        Generator[Any, None, None],
        process_message.handle_stream_message_objects(
            new_msg_req=SendMessageRequest(message="hello"),
            user=_mock_user(),
        ),
    )
    next(stream)
    stream.close()

    assert set(_latency_records_by_function(telemetry_sink)) == {
        "handle_stream_message_objects"
    }
