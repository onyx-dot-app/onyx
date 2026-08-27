"""Guards the per-message capture of what a completion sent to the provider."""

from typing import Any
from unittest.mock import patch

import pytest
from litellm.exceptions import BadRequestError

from onyx.chat.chat_state import ChatStateContainer
from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.request_context import (
    clear_llm_request_params,
    get_llm_request_params,
)

_SENTINEL = object()


@pytest.fixture(autouse=True)
def _clean_context() -> None:
    clear_llm_request_params()


def _make_llm(
    reasoning_effort_max: ReasoningEffort | None = None,
    temperature: float | None = None,
    model_name: str = "gpt-5.1",
) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider="openai",
        model_name=model_name,
        max_input_tokens=100000,
        temperature=temperature,
        reasoning_effort_max=reasoning_effort_max,
    )


def _run(llm: LitellmLLM, effort: ReasoningEffort, completion: Any = None) -> None:
    def default_completion(**_kwargs: Any) -> Any:
        return _SENTINEL

    with patch(
        "onyx.llm.litellm_singleton.litellm.completion",
        side_effect=completion or default_completion,
    ):
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=None,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )


def test_captures_model_identity_and_sent_temperature() -> None:
    _run(_make_llm(temperature=0.3, model_name="gpt-4o"), ReasoningEffort.AUTO)

    params = get_llm_request_params()
    assert params is not None
    assert params["model_name"] == "gpt-4o"
    assert params["model_provider"] == "openai"
    assert params["sent_kwargs"]["temperature"] == 0.3


def test_records_the_pinned_temperature_for_a_reasoning_model() -> None:
    """Reasoning models are pinned to 1 regardless of the configured value, and
    attribution has to show what the provider got, not what was configured."""
    _run(_make_llm(temperature=0.3), ReasoningEffort.HIGH)

    params = get_llm_request_params()
    assert params is not None
    assert params["sent_kwargs"]["temperature"] == 1


def test_captures_the_effort_after_the_admin_cap_applies() -> None:
    """The UI must show what was sent, not what was asked for."""
    _run(_make_llm(reasoning_effort_max=ReasoningEffort.LOW), ReasoningEffort.XHIGH)

    params = get_llm_request_params()
    assert params is not None
    assert params["reasoning_effort"] == "low"


def test_captures_the_attempt_that_returned_after_a_retry() -> None:
    """On a provider 400 the ladder strips kwargs and retries. What is recorded
    must be the attempt that actually came back, not the first one."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "reasoning" in kwargs:
            raise BadRequestError(
                message="reasoning effort not supported",
                model="m",
                llm_provider="openai",
            )
        return _SENTINEL

    _run(_make_llm(), ReasoningEffort.HIGH, completion)

    assert len(calls) == 2
    params = get_llm_request_params()
    assert params is not None
    assert "reasoning" not in params["sent_kwargs"]


def test_tracing_and_capture_receive_the_same_object() -> None:
    """One dict, two sinks, so the chat UI and Braintrust cannot disagree."""
    recorded: list[dict[str, Any]] = []
    with patch(
        "onyx.llm.multi_llm.record_llm_request_params",
        side_effect=lambda p: recorded.append(p),
    ):
        _run(_make_llm(), ReasoningEffort.HIGH)

    assert recorded
    assert recorded[-1] is get_llm_request_params()


def test_non_finite_floats_are_dropped() -> None:
    """These params ride to a JSONB column. Postgres rejects NaN and Infinity,
    so leaving one in would fail the commit that saves the answer."""
    _run(_make_llm(temperature=float("nan"), model_name="gpt-4o"), ReasoningEffort.AUTO)

    params = get_llm_request_params()
    assert params is not None
    assert params["sent_kwargs"]["temperature"] is None


class TestStateContainerHandoff:
    """The value crosses threads via the per-model container, not the contextvar."""

    def test_container_round_trips_the_params(self) -> None:
        container = ChatStateContainer()
        assert container.get_request_params() is None

        container.set_request_params({"model_name": "gpt-5.1"})
        assert container.get_request_params() == {"model_name": "gpt-5.1"}

    def test_container_starts_empty_per_model(self) -> None:
        """Multi-model turns must not share one model's params with another."""
        first = ChatStateContainer()
        second = ChatStateContainer()
        first.set_request_params({"model_name": "gpt-5.1"})

        assert second.get_request_params() is None

    def test_a_later_step_overwrites_an_earlier_one(self) -> None:
        """Tool loops run the step repeatedly. The message is attributed to the
        call that produced the answer, which is the last one to hand off."""
        container = ChatStateContainer()
        container.set_request_params({"model_name": "gpt-5.1", "step": 1})
        container.set_request_params({"model_name": "gpt-5.1", "step": 2})

        assert container.get_request_params() == {"model_name": "gpt-5.1", "step": 2}

    def test_handoff_of_nothing_leaves_it_unset(self) -> None:
        """A turn that fails before any completion attributes nothing, rather
        than inheriting whatever ran previously."""
        container = ChatStateContainer()
        clear_llm_request_params()

        container.set_request_params(get_llm_request_params())

        assert container.get_request_params() is None
