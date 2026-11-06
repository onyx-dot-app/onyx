"""An OnyxError raised while a chat turn is set up keeps its status code:
the non-streaming endpoint raises it, and the streaming endpoint sends it as
an error packet with the same error code."""

import asyncio
import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from onyx.chat import process_message
from onyx.chat.models import ChatTurnSetup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.utils import fleet_query_telemetry

_DETAIL = "Model 'unlisted' is not configured on this provider."


def _request() -> Request:
    return Request(
        scope={
            "app": FastAPI(),
            "type": "http",
            "method": "POST",
            "path": "/chat/send-chat-message",
            "headers": [],
            "query_string": b"",
        }
    )


def _call_endpoint(stream: bool) -> object:
    user = Mock()
    user.is_anonymous = False
    return chat_backend.handle_send_chat_message(
        chat_message_req=SendMessageRequest(message="hello", stream=stream),
        request=_request(),
        user=user,
        _rate_limit_check=None,
        _api_key_usage_check=None,
    )


@pytest.fixture(autouse=True)
def _setup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**_: object) -> ChatTurnSetup:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, _DETAIL)

    monkeypatch.setattr(process_message, "prepare_chat_turn", fail)
    monkeypatch.setattr(
        fleet_query_telemetry, "emit_telemetry", Mock(return_value=True)
    )


def test_non_streaming_raises_setup_error() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _call_endpoint(stream=False)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert exc_info.value.detail == _DETAIL


def test_streaming_sends_setup_error_packet() -> None:
    response = _call_endpoint(stream=True)
    assert isinstance(response, StreamingResponse)

    async def collect() -> list[str]:
        return [
            chunk if isinstance(chunk, str) else bytes(chunk).decode()
            async for chunk in response.body_iterator
        ]

    chunks = asyncio.run(collect())

    assert len(chunks) == 1
    packet = json.loads(chunks[0])
    assert packet["error_code"] == OnyxErrorCode.INVALID_INPUT.code
    assert packet["error"] == _DETAIL
