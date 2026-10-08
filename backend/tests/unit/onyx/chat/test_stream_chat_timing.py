"""Chat timing logs preserve success, failure, and disconnect behavior locally."""

import asyncio
import re
from collections.abc import Generator
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
def timing_sink(monkeypatch: pytest.MonkeyPatch) -> Mock:
    sink = Mock(return_value=None)
    monkeypatch.setattr(timing.logger, "info", sink)
    monkeypatch.setattr(timing.logger, "notice", sink)
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


def _timing_records_by_function(sink: Mock) -> set[str]:
    functions: set[str] = set()
    for call in sink.call_args_list:
        if call.args and call.args[0] == "%s took %s seconds":
            float(call.args[2])
            functions.add(call.args[1])
        elif len(call.args) == 1 and isinstance(call.args[0], str):
            match = re.fullmatch(
                r"([a-zA-Z_][a-zA-Z0-9_]*) took ([0-9.]+) seconds\.", call.args[0]
            )
            if match:
                float(match.group(2))
                functions.add(match.group(1))
    return functions


def test_single_model_stream_logs_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, timing_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(SendMessageRequest(message="hello"))

    # The endpoint returns before the turn runs, so nothing is sent yet.
    assert isinstance(response, StreamingResponse)
    assert not _timing_records_by_function(timing_sink)

    chunks = _drain(response)

    assert len(chunks) == 2
    assert set(_timing_records_by_function(timing_sink)) == {
        "handle_stream_message_objects"
    }


def test_multi_model_stream_logs_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, timing_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(
        SendMessageRequest(
            message="hello",
            llm_overrides=[LLMOverride(), LLMOverride()],
        )
    )

    assert isinstance(response, StreamingResponse)
    assert not _timing_records_by_function(timing_sink)

    chunks = _drain(response)

    assert len(chunks) == 2
    assert set(_timing_records_by_function(timing_sink)) == {
        "handle_multi_model_stream"
    }


def test_non_streaming_logs_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, timing_sink: Mock
) -> None:
    _install_turn(monkeypatch, _two_packet_turn)

    response = _call_endpoint(SendMessageRequest(message="hello", stream=False))

    assert isinstance(response, ChatFullResponse)
    assert response.message_id == 2
    # The turn record plus the aggregation record.
    assert set(_timing_records_by_function(timing_sink)) == {
        "handle_stream_message_objects",
        "gather_stream_full",
    }


def test_stream_failure_still_logs_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, timing_sink: Mock
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
    assert set(_timing_records_by_function(timing_sink)) == {
        "handle_stream_message_objects"
    }


def test_client_disconnect_still_logs_elapsed_time(
    monkeypatch: pytest.MonkeyPatch, timing_sink: Mock
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

    assert set(_timing_records_by_function(timing_sink)) == {
        "handle_stream_message_objects"
    }
