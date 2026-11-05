"""Requests to GPT-5.6+ models on the OpenAI API mark every tool result with an
explicit prompt_cache_breakpoint and send prompt_cache_options."""

import json
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from litellm import ModelResponse as LiteLLMModelResponse
from litellm.exceptions import BadRequestError
from pydantic import JsonValue

from onyx.llm.factory import get_llm
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    Message,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

_RESPONSE = LiteLLMModelResponse(
    id="r",
    created=1,
    choices=[
        {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
    ],
)
_RESULTS = [f"Evidence {index}" for index in range(6)]


def _turn() -> list[Message]:
    messages: list[Message] = [UserMessage(content="Question")]
    for index, text in enumerate(_RESULTS):
        call_id = f"c{index}"
        messages += [
            AssistantMessage(
                content=[ToolCall(id=call_id, name="internal_search", arguments={})]
            ),
            ToolResultMessage(
                content=text, tool_call_id=call_id, tool_name="internal_search"
            ),
        ]
    return [
        *messages,
        UserMessage(content="<system-reminder>Cite sources.</system-reminder>"),
    ]


def _sent(
    provider: str,
    model: str,
    messages: list[Message],
    *,
    api_base: str | None = None,
    custom_config: dict[str, str] | None = None,
    model_kwargs: dict[str, JsonValue] | None = None,
) -> Mapping[str, Any]:
    client = get_llm(
        provider=provider,
        model=model,
        deployment_name=None,
        max_input_tokens=100_000,
        api_base=api_base,
        custom_config=custom_config,
        model_kwargs=model_kwargs,
    )
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion", return_value=_RESPONSE) as completion,
    ):
        client.invoke(GenerationRequest(messages=messages))
    return completion.call_args.kwargs


def _tool_contents(sent: Mapping[str, Any]) -> list[Any]:
    return [m["content"] for m in sent["messages"] if m["role"] == "tool"]


def test_marks_every_tool_result() -> None:
    sent = _sent("openai", "gpt-5.6-luna", _turn())
    assert _tool_contents(sent) == [
        [
            {
                "type": "input_text",
                "text": text,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ]
        for text in _RESULTS
    ]
    assert sent["prompt_cache_options"] == {"mode": "explicit"}
    # The moving reminder itself stays plain text.
    assert sent["messages"][-1]["content"] == (
        "<system-reminder>Cite sources.</system-reminder>"
    )


@pytest.mark.parametrize(
    ("provider", "model", "api_base"),
    [
        ("openai", "gpt-4.1", None),
        ("openai", "gpt-5.5", None),
        ("anthropic", "claude-sonnet-5", None),
        # An OpenAI-compatible server may reject the extra keys.
        ("openai", "gpt-5.6-luna", "https://proxy.example.com/v1"),
    ],
)
def test_other_requests_keep_plain_tool_results(
    provider: str, model: str, api_base: str | None
) -> None:
    sent = _sent(provider, model, _turn(), api_base=api_base)
    assert all(isinstance(content, str) for content in _tool_contents(sent))
    assert "prompt_cache_options" not in sent


def test_disabled_prompt_caching_keeps_plain_tool_results() -> None:
    with patch("onyx.llm.prompt_cache.providers.openai.ENABLE_PROMPT_CACHING", False):
        sent = _sent("openai", "gpt-5.6-luna", _turn())
    assert all(isinstance(content, str) for content in _tool_contents(sent))
    assert "prompt_cache_options" not in sent


def test_no_tool_result_keeps_implicit_caching() -> None:
    sent = _sent("openai", "gpt-5.6-luna", [UserMessage(content="Hello")])
    assert "prompt_cache_options" not in sent


@pytest.mark.parametrize("source", ["custom_config", "api_base", "base_url"])
def test_proxy_overrides_keep_plain_tool_results(source: str) -> None:
    proxy = "https://proxy.example.com/v1"
    sent = _sent(
        "openai",
        "gpt-5.6-luna",
        _turn(),
        custom_config={"OPENAI_API_BASE": proxy} if source == "custom_config" else None,
        model_kwargs={source: proxy} if source != "custom_config" else None,
    )
    assert all(isinstance(content, str) for content in _tool_contents(sent))
    assert "prompt_cache_options" not in sent
    assert sent.get("api_base") == proxy or sent["base_url"] == proxy


def test_cache_options_merge_without_mutating_configuration() -> None:
    configured: dict[str, JsonValue] = {"prompt_cache_options": {"ttl": "1h"}}
    sent = _sent("openai", "gpt-5.6-luna", _turn(), model_kwargs=configured)
    assert sent["prompt_cache_options"] == {"mode": "explicit", "ttl": "1h"}
    sent["prompt_cache_options"]["mode"] = "changed"
    assert configured == {"prompt_cache_options": {"ttl": "1h"}}
    again = _sent("openai", "gpt-5.6-luna", _turn())
    assert again["prompt_cache_options"] == {"mode": "explicit"}


@pytest.mark.parametrize(
    "rejected", ["prompt_cache_options", "prompt_cache_breakpoint"]
)
def test_rejected_cache_options_retry_with_plain_results(rejected: str) -> None:
    attempts: list[dict[str, Any]] = []

    def complete(**kwargs: Any) -> LiteLLMModelResponse:
        attempts.append(kwargs)
        if "prompt_cache_options" in kwargs:
            raise BadRequestError(
                message=f"Unsupported {rejected}",
                model="gpt-5.6-luna",
                llm_provider="openai",
            )
        return _RESPONSE

    client = get_llm(
        provider="openai",
        model="gpt-5.6-luna",
        deployment_name=None,
        max_input_tokens=100_000,
    )
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion", side_effect=complete),
    ):
        client.invoke(GenerationRequest(messages=_turn()))
    assert "prompt_cache_options" in attempts[0]
    assert "prompt_cache_options" not in attempts[-1]
    assert _tool_contents(attempts[-1]) == _RESULTS


def test_real_bridge_preserves_breakpoints_in_responses_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[dict[str, Any]] = []

    def send(
        _client: httpx.Client, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        assert request.url.path == "/v1/responses"
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.6-luna",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "done", "annotations": []}
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
            },
        )

    monkeypatch.setattr(httpx.Client, "send", send)
    client = get_llm(
        provider="openai",
        model="gpt-5.6-luna",
        deployment_name=None,
        api_key="test-key",
        max_input_tokens=100_000,
    )
    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False):
        result = client.invoke(GenerationRequest(messages=_turn()))
    assert result.text == "done"
    assert len(bodies) == 1
    assert bodies[0]["prompt_cache_options"] == {"mode": "explicit"}
    outputs = [
        item["output"]
        for item in bodies[0]["input"]
        if item["type"] == "function_call_output"
    ]
    assert outputs == [
        [
            {
                "type": "input_text",
                "text": text,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ]
        for text in _RESULTS
    ]
