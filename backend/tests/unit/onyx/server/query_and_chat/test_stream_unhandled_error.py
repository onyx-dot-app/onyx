"""An exception that escapes the chat stream handlers must not send its text to
the client. The client gets a stable error packet instead."""

import asyncio
import json
from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import StreamingError

_MARKER = "secret-marker-7f3a /internal/path db_password=hunter2"


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


def _failing_stream(**_: object) -> Iterator[StreamingError]:
    raise RuntimeError(_MARKER)
    yield  # makes this a generator


def _collect(req: SendMessageRequest) -> list[str]:
    user = Mock()
    user.is_anonymous = False
    response = chat_backend.handle_send_chat_message(
        chat_message_req=req,
        request=_request(),
        user=user,
        _rate_limit_check=None,
        _api_key_usage_check=None,
    )
    assert isinstance(response, StreamingResponse)

    async def collect() -> list[str]:
        return [
            chunk if isinstance(chunk, str) else bytes(chunk).decode()
            async for chunk in response.body_iterator
        ]

    return asyncio.run(collect())


@pytest.mark.parametrize("multi_model", [False, True])
def test_unhandled_stream_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, multi_model: bool
) -> None:
    monkeypatch.setattr(chat_backend, "handle_stream_message_objects", _failing_stream)
    monkeypatch.setattr(chat_backend, "handle_multi_model_stream", _failing_stream)
    monkeypatch.setattr(chat_backend, "mt_cloud_telemetry", Mock())

    req = SendMessageRequest(
        message="hello",
        stream=True,
        llm_overrides=(
            [LLMOverride(model_version="a"), LLMOverride(model_version="b")]
            if multi_model
            else None
        ),
    )
    chunks = _collect(req)

    assert len(chunks) == 1
    assert _MARKER not in chunks[0]
    assert "secret-marker" not in chunks[0]
    packet = json.loads(chunks[0])
    assert packet["error_code"] == OnyxErrorCode.INTERNAL_ERROR.code
    assert packet["error"]
    assert packet["stack_trace"] is None
