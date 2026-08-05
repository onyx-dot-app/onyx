"""Guards that generation spans record the requested effort and the kwargs actually sent."""

from typing import Any
from unittest.mock import patch

from litellm.exceptions import BadRequestError

from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.framework.create import generation_span, trace

_SENTINEL = object()


def _make_llm() -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider="anthropic",
        model_name="claude-sonnet-5",
        max_input_tokens=100000,
    )


def _run(completion: Any, effort: ReasoningEffort) -> Any:
    with patch("onyx.llm.litellm_singleton.litellm.completion", side_effect=completion):
        return _make_llm()._completion(
            prompt=[UserMessage(content="hello")],
            tools=None,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )


def test_request_params_recorded_on_generation_span() -> None:
    def completion(**_kwargs: Any) -> Any:
        return _SENTINEL

    with trace("test"), generation_span(model="claude-sonnet-5") as span:
        result = _run(completion, ReasoningEffort.XHIGH)

    assert result is _SENTINEL
    params = span.span_data.request_params
    assert params is not None
    assert params["reasoning_effort"] == "xhigh"
    assert params["sent_kwargs"]["thinking"] == {"type": "adaptive"}
    assert params["sent_kwargs"]["output_config"] == {"effort": "xhigh"}


def test_request_params_reflect_stripped_retry() -> None:
    def completion(**kwargs: Any) -> Any:
        if "thinking" in kwargs or "output_config" in kwargs:
            raise BadRequestError(
                message="effort not supported", model="m", llm_provider="anthropic"
            )
        return _SENTINEL

    with trace("test"), generation_span(model="claude-sonnet-5") as span:
        result = _run(completion, ReasoningEffort.XHIGH)

    assert result is _SENTINEL
    params = span.span_data.request_params
    assert params is not None
    assert params["reasoning_effort"] == "xhigh"
    assert "thinking" not in params["sent_kwargs"]
    assert "output_config" not in params["sent_kwargs"]


def test_request_params_noop_without_span() -> None:
    def completion(**_kwargs: Any) -> Any:
        return _SENTINEL

    assert _run(completion, ReasoningEffort.LOW) is _SENTINEL
