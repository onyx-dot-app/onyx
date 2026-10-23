"""Unit tests for Inworld Router routing in LitellmLLM.

Inworld Router speaks OpenAI chat completions, so it routes through the
OpenAI-compatible surface with a bare `provider/model` id. Its API keys are
Base64 `key:secret` credentials that the router reads from a Basic
Authorization header, which must replace the SDK's default Bearer header.
"""

import json
from unittest.mock import patch

import httpx
import pytest

from onyx.llm.api_surfaces import LlmApiSurface, resolve_api_surface
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import ChatCompletionMessage, UserMessage
from onyx.llm.multi_llm import LitellmLLM


def _make_llm(
    api_key: str | None = "aW53b3JsZDpzZWNyZXQ=",
    api_base: str | None = "https://api.inworld.ai/v1",
    model_name: str = "openai/gpt-5.4",
    extra_headers: dict[str, str] | None = None,
) -> LitellmLLM:
    return LitellmLLM(
        api_key=api_key,
        model_provider=LlmProviderNames.INWORLD,
        model_name=model_name,
        max_input_tokens=128_000,
        api_base=api_base,
        extra_headers=extra_headers,
    )


def _completion_kwargs(llm: LitellmLLM) -> dict:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = []
        messages: list[ChatCompletionMessage] = [UserMessage(content="Hi")]
        list(llm.stream_raw(messages))
        return dict(mock_completion.call_args.kwargs)


def test_routes_through_openai_chat_completions_surface() -> None:
    assert (
        resolve_api_surface(LlmProviderNames.INWORLD, None)
        is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
    )

    kwargs = _completion_kwargs(_make_llm())
    assert kwargs["custom_llm_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.inworld.ai/v1"
    # LiteLLM removes its routing prefix before sending the provider/model id.
    assert kwargs["model"] == "openai/openai/gpt-5.4"


def test_bare_base_is_coerced_to_v1() -> None:
    llm = _make_llm(api_base="https://api.inworld.ai/")
    assert llm._api_base == "https://api.inworld.ai/v1"


def test_auto_router_model_is_sent_as_is() -> None:
    kwargs = _completion_kwargs(_make_llm(model_name="auto"))
    assert kwargs["model"] == "openai/auto"


def test_api_key_is_sent_as_basic_authorization() -> None:
    kwargs = _completion_kwargs(_make_llm())
    assert kwargs["extra_headers"]["Authorization"] == "Basic aW53b3JsZDpzZWNyZXQ="


def test_basic_prefix_in_stored_key_is_not_doubled() -> None:
    kwargs = _completion_kwargs(_make_llm(api_key="Basic aW53b3JsZDpzZWNyZXQ="))
    assert kwargs["extra_headers"]["Authorization"] == "Basic aW53b3JsZDpzZWNyZXQ="


def test_basic_authorization_keeps_other_extra_headers() -> None:
    kwargs = _completion_kwargs(_make_llm(extra_headers={"x-client-request-id": "r1"}))
    assert kwargs["extra_headers"]["x-client-request-id"] == "r1"
    assert kwargs["extra_headers"]["Authorization"] == "Basic aW53b3JsZDpzZWNyZXQ="


def test_no_authorization_header_without_api_key() -> None:
    kwargs = _completion_kwargs(_make_llm(api_key=None))
    assert "Authorization" not in (kwargs.get("extra_headers") or {})


def test_other_openai_compatible_providers_keep_bearer_auth() -> None:
    llm = LitellmLLM(
        api_key="sk-test",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name="gpt-4o",
        max_input_tokens=128_000,
        api_base="http://localhost:8000/v1",
    )
    kwargs = _completion_kwargs(llm)
    assert "Authorization" not in (kwargs.get("extra_headers") or {})


@pytest.mark.parametrize(
    "model_name",
    [
        "openai/gpt-5-mini",
        "anthropic/claude-haiku-4-5",
        "inworld/models/inworld-llm-small",
        "auto",
    ],
)
def test_sdk_transport_preserves_basic_auth_and_streamed_tool_calls(
    model_name: str,
) -> None:
    """Exercise LiteLLM and the OpenAI SDK, mocking only the HTTP transport."""
    sent: list[httpx.Request] = []
    deltas = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_weather",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city":'},
                }
            ],
        },
        {"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]},
        {},
    ]
    events = [
        {
            "id": "chatcmpl-inworld-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "openai/gpt-5-mini",
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": "tool_calls" if index == 2 else None,
                }
            ],
        }
        for index, delta in enumerate(deltas)
    ]
    stream = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    stream += "data: [DONE]\n\n"

    def respond(
        _client: httpx.Client, request: httpx.Request, **_kwargs: object
    ) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=stream.encode(),
            request=request,
        )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    with patch("httpx.Client.send", autospec=True, side_effect=respond):
        chunks = list(
            _make_llm(model_name=model_name).stream_raw(
                [UserMessage(content="Get the weather in Paris")], tools=tools
            )
        )

    assert len(sent) == 1
    assert str(sent[0].url) == "https://api.inworld.ai/v1/chat/completions"
    assert sent[0].headers.get_list("Authorization") == ["Basic aW53b3JsZDpzZWNyZXQ="]
    body = json.loads(sent[0].content)
    assert body["model"] == model_name
    assert body["tools"] == tools
    assert body["stream"] is True
    calls = [call for chunk in chunks for call in chunk.choice.delta.tool_calls]
    assert calls[0].id == "call_weather"
    assert calls[0].function is not None
    assert calls[0].function.name == "get_weather"
    arguments = "".join(
        call.function.arguments or "" for call in calls if call.function is not None
    )
    assert json.loads(arguments) == {"city": "Paris"}
