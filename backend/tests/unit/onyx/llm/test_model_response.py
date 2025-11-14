from __future__ import annotations

from typing import cast
from typing import TYPE_CHECKING

import pytest

from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import from_litellm_model_response
from onyx.llm.model_response import from_litellm_model_response_stream
from onyx.llm.model_response import FunctionCall
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream

if TYPE_CHECKING:
    from litellm.types.utils import (
        ModelResponse as LiteLLMModelResponse,
        ModelResponseStream as LiteLLMModelResponseStream,
    )


class _LiteLLMStreamDouble:
    """
    Lightweight double that mimics the LiteLLM ``ModelResponseStream`` interface
    used by ``from_litellm_model_response_stream``.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return self._payload


class _LiteLLMResponseDouble:
    """
    Lightweight double that mimics the LiteLLM ``ModelResponse`` interface
    used by ``from_litellm_model_response``.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self) -> dict:
        return self._payload


def _make_stream_double(payload: dict) -> "LiteLLMModelResponseStream":
    """Create a test double for LiteLLM ModelResponseStream."""
    return cast("LiteLLMModelResponseStream", _LiteLLMStreamDouble(payload))


def _make_response_double(payload: dict) -> "LiteLLMModelResponse":
    """Create a test double for LiteLLM ModelResponse."""
    return cast("LiteLLMModelResponse", _LiteLLMResponseDouble(payload))


def _build_tool_call_payload() -> dict:
    return {
        "id": "chatcmpl-f739f09c-7c9b-4dd6-aea7-cf41d4fd2196",
        "created": 1762544538,
        "model": "gpt-5",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": None,
                            "index": 0,
                            "type": "function",
                            "function": {
                                "arguments": '{"',
                                "name": None,
                            },
                        }
                    ],
                },
            }
        ],
    }


def _build_reasoning_payload() -> dict:
    return {
        "id": "chatcmpl-c2a25682-5715-4ca2-84a9-061498f79626",
        "created": 1762544538,
        "model": "gpt-5",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "reasoning_content": " variations",
                },
            }
        ],
    }


def _build_finish_reason_payload() -> tuple[dict, dict]:
    base_chunk = {
        "id": "chatcmpl-2b136068-c6fb-4af1-97d5-d2c9d84cd52b",
        "created": 1762544448,
        "object": "chat.completion.chunk",
    }

    content_chunk = base_chunk | {
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "content": "?",
                },
            }
        ],
    }

    final_chunk = base_chunk | {
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "delta": {},
            }
        ],
    }

    return content_chunk, final_chunk


def _build_multiple_tool_calls_payload() -> dict:
    return {
        "id": "Yn4SaajROLXEnvgP5JTN-AQ",
        "created": 1762819684,
        "model": "gemini-2.5-flash",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "finish_reason": None,
                "index": 0,
                "delta": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_130bec4755e544ea95f4b1bafd81",
                            "function": {
                                "arguments": '{"queries": ["new agent framework"]}',
                                "name": "internal_search",
                            },
                            "type": "function",
                            "index": 0,
                        },
                        {
                            "id": "call_42273e8ee5ac4c0a97237d6d25a6",
                            "function": {
                                "arguments": '{"queries": ["cheese"]}',
                                "name": "web_search",
                            },
                            "type": "function",
                            "index": 1,
                        },
                    ],
                },
            }
        ],
    }


def _build_non_streaming_response_payload() -> dict:
    return {
        "id": "chatcmpl-abc123",
        "created": 1234567890,
        "model": "gpt-4",
        "object": "chat.completion",
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {
                    "content": "Hello, world!",
                    "role": "assistant",
                },
            }
        ],
    }


def _build_non_streaming_tool_call_payload() -> dict:
    return {
        "id": "chatcmpl-xyz789",
        "created": 9876543210,
        "model": "gpt-4",
        "object": "chat.completion",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "index": 0,
                "message": {
                    "content": None,
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "search_documents",
                                "arguments": '{"query": "test"}',
                            },
                        }
                    ],
                },
            }
        ],
    }


def test_from_litellm_model_response_stream_parses_tool_calls() -> None:
    response = from_litellm_model_response_stream(
        _make_stream_double(_build_tool_call_payload())
    )

    assert isinstance(response, ModelResponseStream)
    assert response.id == "chatcmpl-f739f09c-7c9b-4dd6-aea7-cf41d4fd2196"
    assert response.created == "1762544538"

    tool_calls = response.choice.delta.tool_calls
    assert len(tool_calls) == 1
    assert tool_calls[0] == ChatCompletionDeltaToolCall(
        id=None,
        index=0,
        type="function",
        function=FunctionCall(arguments='{"', name=None),
    )


def test_from_litellm_model_response_stream_preserves_reasoning_content() -> None:
    response = from_litellm_model_response_stream(
        _make_stream_double(_build_reasoning_payload())
    )

    assert response.choice.delta.content is None
    assert response.choice.delta.reasoning_content == " variations"
    assert response.choice.finish_reason is None


@pytest.mark.parametrize("payload", _build_finish_reason_payload())
def test_from_litellm_model_response_stream_handles_content_and_finish_reason(
    payload: dict,
) -> None:
    response = from_litellm_model_response_stream(_make_stream_double(payload))

    assert response.id == "chatcmpl-2b136068-c6fb-4af1-97d5-d2c9d84cd52b"
    assert response.created == "1762544448"
    assert response.choice.index == 0
    if payload["choices"][0]["finish_reason"] == "stop":
        assert response.choice.finish_reason == "stop"
        assert response.choice.delta.content is None
    else:
        assert response.choice.finish_reason is None
        assert response.choice.delta.content == "?"


def test_from_litellm_model_response_stream_parses_multiple_tool_calls() -> None:
    response = from_litellm_model_response_stream(
        _make_stream_double(_build_multiple_tool_calls_payload())
    )

    tool_calls = response.choice.delta.tool_calls
    assert response.id == "Yn4SaajROLXEnvgP5JTN-AQ"
    assert response.created == "1762819684"
    assert response.choice.finish_reason is None
    assert response.choice.delta.content is None
    assert len(tool_calls) == 2
    assert tool_calls[0] == ChatCompletionDeltaToolCall(
        id="call_130bec4755e544ea95f4b1bafd81",
        index=0,
        type="function",
        function=FunctionCall(
            arguments='{"queries": ["new agent framework"]}',
            name="internal_search",
        ),
    )
    assert tool_calls[1] == ChatCompletionDeltaToolCall(
        id="call_42273e8ee5ac4c0a97237d6d25a6",
        index=1,
        type="function",
        function=FunctionCall(
            arguments='{"queries": ["cheese"]}',
            name="web_search",
        ),
    )


def test_from_litellm_model_response_parses_basic_message() -> None:
    response = from_litellm_model_response(
        _make_response_double(_build_non_streaming_response_payload())
    )

    assert isinstance(response, ModelResponse)
    assert response.id == "chatcmpl-abc123"
    assert response.created == "1234567890"
    assert response.choice.finish_reason == "stop"
    assert response.choice.message.content == "Hello, world!"
    assert response.choice.message.role == "assistant"
    assert response.choice.message.tool_calls is None


def test_from_litellm_model_response_parses_tool_calls() -> None:
    response = from_litellm_model_response(
        _make_response_double(_build_non_streaming_tool_call_payload())
    )

    assert isinstance(response, ModelResponse)
    assert response.id == "chatcmpl-xyz789"
    assert response.created == "9876543210"
    assert response.choice.finish_reason == "tool_calls"
    assert response.choice.message.content is None
    assert response.choice.message.role == "assistant"
    assert response.choice.message.tool_calls is not None
    assert len(response.choice.message.tool_calls) == 1

    tool_call = response.choice.message.tool_calls[0]
    assert tool_call.id == "call_abc123"
    assert tool_call.type == "function"
    assert tool_call.function.name == "search_documents"
    assert tool_call.function.arguments == '{"query": "test"}'
