"""The reasoning effort a user picks must reach models behind an
OpenAI-compatible provider: Claude past a finished tool turn, GPT-5.4+ tool
turns LiteLLM bridges to responses, and models only the admin flags as
reasoning."""

from typing import Any
from unittest.mock import patch

from litellm.exceptions import BadRequestError

from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_request import (
    AssistantMessage,
    ChatCompletionMessage,
    RequestFunctionCall,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from onyx.llm.models import ReasoningEffort
from onyx.llm.multi_llm import LitellmLLM

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]

_TOOL_LOOP: list[ChatCompletionMessage] = [
    UserMessage(content="hi"),
    AssistantMessage(
        content=None,
        tool_calls=[
            ToolCall(
                id="c1", function=RequestFunctionCall(name="search", arguments="{}")
            )
        ],
    ),
    ToolMessage(content="result", tool_call_id="c1"),
]

_NEXT_TURN: list[ChatCompletionMessage] = [
    *_TOOL_LOOP,
    AssistantMessage(content="answer"),
    UserMessage(content="follow-up"),
]


def _llm(model_name: str, supports_reasoning: bool = False) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name=model_name,
        max_input_tokens=100000,
        api_base="https://gateway.example/v1",
        supports_reasoning=supports_reasoning,
    )


def _sent_kwargs(
    llm: LitellmLLM,
    prompt: list[ChatCompletionMessage],
    tools: list[dict[str, Any]] | None = _TOOLS,
) -> dict[str, Any]:
    with patch("onyx.llm.litellm_singleton.litellm.completion") as completion:
        llm._completion(
            prompt=prompt,
            tools=tools,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.HIGH,
        )
    return dict(completion.call_args.kwargs)


def test_claude_keeps_reasoning_after_a_finished_tool_turn() -> None:
    kwargs = _sent_kwargs(_llm("claude-sonnet-5"), _NEXT_TURN)
    assert kwargs["reasoning"] == {"effort": "high", "summary": "auto"}


def test_claude_skips_reasoning_inside_a_tool_loop() -> None:
    """The gateway cannot replay the signed thinking block Anthropic needs."""
    kwargs = _sent_kwargs(_llm("claude-sonnet-5"), _TOOL_LOOP)
    assert "reasoning" not in kwargs


def test_gpt_5_5_tool_turn_keeps_effort_for_the_responses_bridge() -> None:
    kwargs = _sent_kwargs(_llm("gpt-5.5"), _TOOL_LOOP)
    assert kwargs["reasoning_effort"] == {"effort": "high", "summary": "auto"}
    assert "reasoning" not in kwargs


def test_bridged_effort_survives_the_retry_ladder() -> None:
    """Without reasoning_effort LiteLLM keeps the call on chat completions,
    where GPT-5.4+ reject the tools."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise BadRequestError(
                message="temperature is not supported", model="m", llm_provider="openai"
            )
        return None

    with patch("onyx.llm.litellm_singleton.litellm.completion", side_effect=completion):
        _llm("gpt-5.5")._completion(
            prompt=_TOOL_LOOP,
            tools=_TOOLS,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.HIGH,
        )

    assert len(calls) == 2
    assert "temperature" not in calls[1]
    assert calls[1]["reasoning_effort"] == {"effort": "high", "summary": "auto"}


def test_admin_flagged_model_gets_effort_past_drop_params() -> None:
    """LiteLLM drops reasoning_effort for models it does not list as reasoning
    models unless it is allowed explicitly."""
    kwargs = _sent_kwargs(_llm("gemini-3.1-pro", supports_reasoning=True), _TOOL_LOOP)
    assert kwargs["reasoning_effort"] == "high"
    assert "reasoning_effort" in kwargs["allowed_openai_params"]


def test_admin_flagged_gpt_6_gets_effort_without_tools() -> None:
    kwargs = _sent_kwargs(
        _llm("gpt-6", supports_reasoning=True), [UserMessage(content="hi")], None
    )
    assert kwargs["reasoning_effort"] == "high"
    assert "reasoning_effort" in kwargs["allowed_openai_params"]


def test_gpt_6_tool_turn_delivers_explicit_none() -> None:
    """GPT-6 tool turns stay on chat completions, which need "none"; LiteLLM
    must not drop it."""
    kwargs = _sent_kwargs(_llm("gpt-6", supports_reasoning=True), _TOOL_LOOP)
    assert kwargs["reasoning_effort"] == "none"
    assert "reasoning_effort" in kwargs["allowed_openai_params"]


def test_unflagged_unknown_model_sends_no_effort() -> None:
    kwargs = _sent_kwargs(_llm("gemini-3.1-pro"), [UserMessage(content="hi")], None)
    assert "reasoning_effort" not in kwargs
