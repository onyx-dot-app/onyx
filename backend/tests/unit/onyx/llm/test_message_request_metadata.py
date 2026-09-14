"""Guards the per-message capture of what a completion sent to the provider."""

from collections.abc import Callable, Iterator
from unittest.mock import patch

from litellm import ModelResponse
from litellm.exceptions import BadRequestError
from pydantic import JsonValue

from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    GenerationRequestParams,
    ReasoningEffort,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport


def _make_llm(
    reasoning_effort_max: ReasoningEffort | None = None,
    temperature: float | None = None,
    model_name: str = "gpt-5.1",
) -> LitellmTransport:
    return LitellmTransport(
        api_key="test-key",
        model_provider="openai",
        model_name=model_name,
        max_input_tokens=100000,
        temperature=temperature,
        reasoning_effort_max=reasoning_effort_max,
    )


def _run(
    llm: LitellmTransport,
    effort: ReasoningEffort,
    completion: Callable[[dict[str, JsonValue]], None] | None = None,
) -> GenerationRequestParams:
    class Response(Iterator[ModelResponse]):
        def __init__(
            self,
            kwargs: dict[str, JsonValue],
            signal: CancellationSignal,
            *,
            timeout: float,
            isolated_client: bool,
        ) -> None:
            del signal, timeout, isolated_client
            if completion is not None:
                completion(kwargs)
            self.sent = False

        def __iter__(self) -> "Response":
            return self

        def __next__(self) -> ModelResponse:
            if self.sent:
                raise StopIteration
            self.sent = True
            return ModelResponse(
                stream=True,
                choices=[
                    {
                        "index": 0,
                        "delta": {"content": "answer"},
                        "finish_reason": "stop",
                    }
                ],
            )

        def close(self) -> None:
            pass

    with patch("onyx.llm.multi_llm.CancellableStream", Response):
        events = list(
            LitellmLLM(llm).stream(
                GenerationRequest(
                    messages=[UserMessage(content="hello")],
                    options=GenerationOptions(reasoning_effort=effort),
                )
            )
        )
    params = events[-1].request_params
    assert params is not None
    return params


def test_captures_model_identity_and_sent_temperature() -> None:
    params = _run(_make_llm(temperature=0.3, model_name="gpt-4o"), ReasoningEffort.AUTO)

    assert params is not None
    assert params.model_name == "gpt-4o"
    assert params.model_provider == "openai"
    assert params.sent_kwargs["temperature"] == 0.3


def test_records_the_pinned_temperature_for_a_reasoning_model() -> None:
    """Diagnostics record the provider's effective temperature."""
    params = _run(_make_llm(temperature=0.3), ReasoningEffort.HIGH)

    assert params is not None
    assert params.sent_kwargs["temperature"] == 1


def test_captures_the_effort_after_the_admin_cap_applies() -> None:
    """The UI must show what was sent, not what was asked for."""
    params = _run(
        _make_llm(reasoning_effort_max=ReasoningEffort.LOW), ReasoningEffort.XHIGH
    )

    assert params is not None
    assert params.reasoning_effort == "low"


def test_captures_the_attempt_that_returned_after_a_retry() -> None:
    """Diagnostics reflect the successful attempt's stripped options."""
    calls: list[dict[str, JsonValue]] = []

    def completion(kwargs: dict[str, JsonValue]) -> None:
        calls.append(kwargs)
        if "reasoning" in kwargs:
            raise BadRequestError(
                message="reasoning effort not supported",
                model="m",
                llm_provider="openai",
            )
        return None

    params = _run(_make_llm(), ReasoningEffort.HIGH, completion)

    assert len(calls) == 2
    assert params is not None
    assert "reasoning" not in params.sent_kwargs


def test_tracing_and_events_receive_the_same_parameters() -> None:
    """Trace and display consumers receive the effective request parameters."""
    recorded: list[GenerationRequestParams] = []
    with patch(
        "onyx.llm.multi_llm.record_llm_request_params",
        side_effect=lambda p: recorded.append(p),
    ):
        params = _run(_make_llm(), ReasoningEffort.HIGH)

    assert recorded
    assert recorded[-1] == params


def test_non_finite_floats_are_dropped() -> None:
    """Postgres JSONB rejects non-finite numbers."""
    params = _run(
        _make_llm(temperature=float("nan"), model_name="gpt-4o"), ReasoningEffort.AUTO
    )

    assert params is not None
    assert params.sent_kwargs["temperature"] is None


def test_nested_generations_keep_their_request_parameters() -> None:
    nested: list[GenerationRequestParams] = []

    def completion(_kwargs: dict[str, JsonValue]) -> None:
        nested.append(
            _run(_make_llm(temperature=0.7, model_name="gpt-4o"), ReasoningEffort.AUTO)
        )

    outer = _run(
        _make_llm(temperature=0.3, model_name="gpt-4o"),
        ReasoningEffort.AUTO,
        completion,
    )
    assert outer.sent_kwargs["temperature"] == 0.3
    assert nested[0].sent_kwargs["temperature"] == 0.7
