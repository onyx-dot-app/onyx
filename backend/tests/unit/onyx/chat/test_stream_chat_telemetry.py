"""Verify every path through the send-message endpoint emits one ``query`` record.

``handle_send_chat_message`` fans out to three flows: single-model streaming,
multi-model streaming, and the non-streaming API. Each flow ends in a generator
decorated with ``telemetry_chat``. These tests call the endpoint directly with
the LLM turn stubbed out and assert the telemetry record for each flow, plus
the failure and client-disconnect exits.
"""

import asyncio
from collections.abc import Generator
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse

from onyx.chat import process_message
from onyx.chat.models import AnswerStream, ChatFullResponse, StreamingError
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.utils import fleet_query_telemetry

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


@pytest.fixture
def telemetry_sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    # The decorator resolves ``emit_telemetry`` from its own module's namespace,
    # so patch it there rather than in ``onyx.utils.fleet_telemetry``.
    sink = Mock(return_value=True)
    monkeypatch.setattr(fleet_query_telemetry, "emit_telemetry", sink)
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


def _query_outcomes(sink: Mock) -> list[str]:
    outcomes: list[str] = []
    for call in sink.call_args_list:
        event_type, data = call.args
        assert event_type == "query"
        assert data["channel"] == "web" and data["mode"] == "chat"
        # Records never carry the user.
        assert _USER_ID not in str(data)
        outcomes.append(data["outcome"])
    return outcomes


def test_single_model_stream_emits_query_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(SendMessageRequest(message="hello"))

    # The endpoint returns before the turn runs, so nothing is sent yet.
    assert isinstance(response, StreamingResponse)
    telemetry_sink.assert_not_called()

    chunks = _drain(response)

    assert len(chunks) == 2
    assert _query_outcomes(telemetry_sink) == ["success"]


def test_multi_model_stream_emits_query_record(
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
    assert _query_outcomes(telemetry_sink) == ["success"]


def test_non_streaming_emits_query_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(SendMessageRequest(message="hello", stream=False))

    assert isinstance(response, ChatFullResponse)
    assert response.message_id == 2
    assert _query_outcomes(telemetry_sink) == ["success"]


def test_stream_failure_still_emits_query_record(
    monkeypatch: pytest.MonkeyPatch, telemetry_sink: Mock
) -> None:
    # ``_stream_chat_turn`` sends each error as a final ``StreamingError``.
    def failing_turn(**_: Any) -> AnswerStream:
        yield _packet()
        yield StreamingError(
            error="llm exploded",
            error_code="RATE_LIMIT",
            details={"model": "gpt-4o", "provider": "openai"},
        )

    _install_turn(monkeypatch, failing_turn)

    response = _call_endpoint(SendMessageRequest(message="hello"))
    assert isinstance(response, StreamingResponse)

    chunks = _drain(response)

    assert len(chunks) == 2
    assert "llm exploded" in chunks[-1]
    assert _query_outcomes(telemetry_sink) == ["failure"]
    # The record names the error category, never its message.
    assert telemetry_sink.call_args.args[1]["error_code"] == "rate_limit"
    assert "llm exploded" not in str(telemetry_sink.call_args)


def test_client_disconnect_still_emits_query_record(
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

    assert _query_outcomes(telemetry_sink) == ["disconnected"]
