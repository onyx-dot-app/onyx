"""Requests to GPT-5.6+ models on the OpenAI API mark every tool result with an
explicit prompt_cache_breakpoint and send prompt_cache_options."""

from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

import pytest
from litellm import ModelResponse as LiteLLMModelResponse

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
) -> Mapping[str, Any]:
    client = get_llm(
        provider=provider,
        model=model,
        deployment_name=None,
        max_input_tokens=100_000,
        api_base=api_base,
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
