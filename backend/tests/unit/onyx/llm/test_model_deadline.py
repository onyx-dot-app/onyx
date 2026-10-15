"""Generation deadlines stop cooperative work and preserve parent runs."""

import threading
from unittest.mock import patch

import pytest

from onyx.llm.cancellation import (
    CancellationSignal,
    current_cancellation,
)
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import GenerationRequest
from onyx.llm.multi_llm import LitellmLLM


@pytest.mark.parametrize("streaming", [False, True])
def test_deadline_stops_cooperative_provider_call(streaming: bool) -> None:
    cleaned_up = threading.Event()
    parent = CancellationSignal()
    client = LitellmLLM(
        api_key="test-key",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
    )

    def pending_response(**_kwargs: object) -> None:
        signal = current_cancellation()
        assert signal is not None
        try:
            clock.return_value += 1
            signal.check()
        finally:
            cleaned_up.set()

    context = GenerationContext(cancellation=parent, total_timeout_s=0.05)
    with (
        patch("onyx.llm.litellm_singleton.litellm.completion", pending_response),
        patch("onyx.llm.multi_llm.time.monotonic", return_value=10.0) as clock,
    ):
        with pytest.raises(LLMTimeoutError, match="total timeout"):
            if streaming:
                list(client.stream(GenerationRequest(), context))
            else:
                client.invoke(GenerationRequest(), context)
    assert cleaned_up.is_set()
    assert not parent.cancelled


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("rate_limit", [False, True])
def test_public_calls_normalize_provider_failures(
    streaming: bool, rate_limit: bool
) -> None:
    from litellm.exceptions import RateLimitError, Timeout

    from onyx.llm.exceptions import LLMRateLimitError

    client = LitellmLLM(
        api_key="test-key",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
    )
    error_type = RateLimitError if rate_limit else Timeout
    expected = LLMRateLimitError if rate_limit else LLMTimeoutError
    failure = error_type(
        message="provider error", model="gpt-5-mini", llm_provider="openai"
    )
    method = "stream_raw" if streaming else "invoke_raw"
    with patch.object(client, method, side_effect=failure):
        with pytest.raises(expected, match="provider error"):
            if streaming:
                list(client.stream(GenerationRequest()))
            else:
                client.invoke(GenerationRequest())


def test_nested_cancel_listener_keeps_outer_registration() -> None:
    signal = CancellationSignal()
    cancelled = threading.Event()
    with signal.on_cancel(cancelled.set):
        with signal.on_cancel(cancelled.set):
            pass
        signal.cancel()
    assert cancelled.is_set()
