"""`_completion` must send an explicit reasoning_effort "none" when GPT-5.4+ take
function tools over chat completions, and leave responses routes and older
models alone."""

from typing import Any
from unittest.mock import patch

from litellm.exceptions import BadRequestError

from onyx.llm.constants import LlmProviderNames
from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import (
    BIFROST_API_MODE_CHAT_COMPLETIONS,
    BIFROST_API_MODE_CONFIG_KEY,
    BIFROST_API_MODE_RESPONSES,
)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _bifrost_llm(model_name: str, api_mode: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=LlmProviderNames.BIFROST,
        model_name=model_name,
        max_input_tokens=100000,
        api_base="https://bifrost.example/v1",
        custom_config={BIFROST_API_MODE_CONFIG_KEY: api_mode},
    )


def _azure_llm(model_name: str) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=LlmProviderNames.AZURE,
        model_name=model_name,
        max_input_tokens=100000,
        api_base="https://example.openai.azure.com",
        api_version="2025-04-01-preview",
    )


def _sent_kwargs(
    llm: LitellmLLM,
    tools: list[dict] | None,
    effort: ReasoningEffort = ReasoningEffort.AUTO,
) -> dict[str, Any]:
    with patch("onyx.llm.litellm_singleton.litellm.completion") as completion:
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=tools,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )
    return dict(completion.call_args.kwargs)


def test_chat_completions_tools_send_explicit_none() -> None:
    kwargs = _sent_kwargs(
        _bifrost_llm("openai/gpt-5.6-sol", BIFROST_API_MODE_CHAT_COMPLETIONS), _TOOLS
    )
    assert kwargs["reasoning_effort"] == "none"
    assert "reasoning" not in kwargs


def test_off_still_sends_explicit_none_with_tools() -> None:
    """OFF normally omits every reasoning kwarg, which these models reject."""
    kwargs = _sent_kwargs(
        _bifrost_llm("openai/gpt-5.6-sol", BIFROST_API_MODE_CHAT_COMPLETIONS),
        _TOOLS,
        ReasoningEffort.OFF,
    )
    assert kwargs["reasoning_effort"] == "none"


def test_chat_completions_without_tools_keeps_reasoning() -> None:
    kwargs = _sent_kwargs(
        _bifrost_llm("openai/gpt-5.6-sol", BIFROST_API_MODE_CHAT_COMPLETIONS), None
    )
    assert kwargs["reasoning"]["effort"] == "medium"
    assert "reasoning_effort" not in kwargs


def test_responses_surface_keeps_reasoning_with_tools() -> None:
    kwargs = _sent_kwargs(
        _bifrost_llm("openai/gpt-5.6-sol", BIFROST_API_MODE_RESPONSES), _TOOLS
    )
    assert kwargs["reasoning"]["effort"] == "medium"
    assert "reasoning_effort" not in kwargs


def test_older_models_keep_reasoning_with_tools() -> None:
    kwargs = _sent_kwargs(
        _bifrost_llm("openai/gpt-5.2", BIFROST_API_MODE_CHAT_COMPLETIONS), _TOOLS
    )
    assert kwargs["reasoning"]["effort"] == "medium"
    assert "reasoning_effort" not in kwargs


def test_azure_deployment_alias_sends_explicit_none() -> None:
    """An alias the registry doesn't know takes Azure chat completions, where
    the model rejects the tools even with no reasoning kwarg at all."""
    kwargs = _sent_kwargs(_azure_llm("gpt-5.6-sol-01-ptu"), _TOOLS)
    assert kwargs["model"] == "azure/gpt-5.6-sol-01-ptu"
    assert kwargs["reasoning_effort"] == "none"
    assert "reasoning" not in kwargs


def test_azure_registry_model_keeps_reasoning_on_responses_bridge() -> None:
    kwargs = _sent_kwargs(_azure_llm("gpt-5.6-sol"), _TOOLS)
    assert kwargs["model"] == "azure/responses/gpt-5.6-sol"
    assert kwargs["reasoning"]["effort"] == "medium"
    assert "reasoning_effort" not in kwargs


def test_forced_none_survives_the_retry_ladder() -> None:
    """A rejection of another optional kwarg must not strip the required "none"
    on retry, or the retry hits the 400 that value exists to avoid."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise BadRequestError(
                message="temperature is not supported", model="m", llm_provider="openai"
            )
        return None

    llm = _bifrost_llm("openai/gpt-5.6-sol", BIFROST_API_MODE_CHAT_COMPLETIONS)
    with patch("onyx.llm.litellm_singleton.litellm.completion", side_effect=completion):
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=_TOOLS,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.AUTO,
        )

    assert len(calls) == 2
    assert "temperature" in calls[0] and "temperature" not in calls[1]
    assert calls[0]["reasoning_effort"] == "none"
    assert calls[1]["reasoning_effort"] == "none"


def test_opaque_alias_learns_none_from_the_rejection() -> None:
    """An alias with no version in its name cannot be matched by name, so the
    ladder must send "none" once the provider demands it, keeping the rest."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if kwargs.get("reasoning_effort") != "none":
            raise BadRequestError(
                message=(
                    "Function tools with reasoning_effort are not supported for "
                    "prod-gpt in /v1/chat/completions. To use function tools, use "
                    "/v1/responses or set reasoning_effort to 'none'."
                ),
                model="m",
                llm_provider="azure",
            )
        return None

    llm = _azure_llm("prod-gpt")
    with patch("onyx.llm.litellm_singleton.litellm.completion", side_effect=completion):
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=_TOOLS,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.AUTO,
        )

    assert len(calls) == 2
    assert "reasoning_effort" not in calls[0]
    assert calls[1]["reasoning_effort"] == "none"
    assert calls[1]["temperature"] == calls[0]["temperature"]
