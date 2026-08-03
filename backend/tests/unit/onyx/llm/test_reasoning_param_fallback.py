"""Guards the degrade-and-retry behavior for provider-rejected reasoning params."""

from typing import Any
from unittest.mock import patch

import pytest
from litellm.exceptions import BadRequestError, RateLimitError

from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.llm.multi_llm import LitellmLLM, LLMRateLimitError

_SENTINEL = object()


def _make_llm(
    model_name: str = "claude-sonnet-5", model_provider: str = "anthropic"
) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=100000,
    )


def _bad_request(message: str = "effort not supported") -> BadRequestError:
    return BadRequestError(message=message, model="m", llm_provider="anthropic")


def _run(
    llm: LitellmLLM, completion: Any, effort: ReasoningEffort, stream: bool = False
) -> Any:
    with patch("onyx.llm.litellm_singleton.litellm.completion", side_effect=completion):
        return llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=None,
            tool_choice=None,
            stream=stream,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )


def test_rejected_reasoning_params_are_stripped_and_retried() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "thinking" in kwargs or "output_config" in kwargs:
            raise _bad_request()
        return _SENTINEL

    result = _run(_make_llm(), completion, ReasoningEffort.XHIGH)

    assert result is _SENTINEL
    assert len(calls) == 2
    assert "thinking" in calls[0] or "output_config" in calls[0]
    for key in ("thinking", "output_config", "reasoning", "reasoning_effort"):
        assert key not in calls[1]


def test_bad_request_without_reasoning_params_raises() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise _bad_request("bad prompt")

    # OFF sends no reasoning kwargs and claude-sonnet-5 omits temperature,
    # so nothing is strippable.
    with pytest.raises(BadRequestError):
        _run(_make_llm(), completion, ReasoningEffort.OFF)
    assert len(calls) == 1


def test_bad_request_after_strip_propagates() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise _bad_request("thinking is not supported on this endpoint")

    with pytest.raises(BadRequestError):
        _run(_make_llm(), completion, ReasoningEffort.HIGH)
    assert len(calls) == 2


def test_unrelated_bad_request_is_not_retried() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise _bad_request("prompt is too long: 250000 tokens > 200000 maximum")

    # The 400 names no strippable kwarg, so the ladder must not burn retries.
    with pytest.raises(BadRequestError):
        _run(_make_llm(), completion, ReasoningEffort.HIGH)
    assert len(calls) == 1


def test_ladder_strips_reasoning_then_all_best_effort_kwargs() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "reasoning" in kwargs:
            raise _bad_request("reasoning is not supported with this model")
        if "temperature" in kwargs:
            raise _bad_request("temperature is not supported with this model")
        return _SENTINEL

    # gpt-5.4 sets both a reasoning kwarg and temperature, exercising the
    # full three-attempt ladder.
    result = _run(
        _make_llm(model_name="gpt-5.4", model_provider="openai"),
        completion,
        ReasoningEffort.HIGH,
    )

    assert result is _SENTINEL
    assert len(calls) == 3
    assert "reasoning" in calls[0] and "temperature" in calls[0]
    assert "reasoning" not in calls[1] and "temperature" in calls[1]
    assert "reasoning" not in calls[2] and "temperature" not in calls[2]


def test_rejected_sampling_params_retry_without_reasoning_tier() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise _bad_request("temperature not supported")
        return _SENTINEL

    # A non-reasoning model sends temperature but no reasoning kwargs, so the
    # ladder has exactly one fallback step.
    result = _run(
        _make_llm(model_name="gpt-4.1", model_provider="openai"),
        completion,
        ReasoningEffort.AUTO,
    )

    assert result is _SENTINEL
    assert len(calls) == 2
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]


def test_stream_options_rejection_is_not_retried() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise _bad_request("stream_options is not supported with this model")

    # Only reasoning kwargs and temperature are strippable, so a 400 naming
    # stream_options surfaces immediately.
    with pytest.raises(BadRequestError):
        _run(_make_llm(), completion, ReasoningEffort.OFF, stream=True)
    assert len(calls) == 1
    assert "stream_options" in calls[0]


def test_rate_limit_is_not_retried() -> None:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise RateLimitError(message="slow down", model="m", llm_provider="anthropic")

    with pytest.raises(LLMRateLimitError):
        _run(_make_llm(), completion, ReasoningEffort.HIGH)
    assert len(calls) == 1
