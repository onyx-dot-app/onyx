"""Generation tracing at the public model client boundary."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.llm.models import GenerationRequest, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import generation_span, trace


def test_trace_configuration_and_errors_exclude_credentials() -> None:
    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key="test-private-key",
        custom_config={"custom_api_key": "test-custom-secret"},
        max_input_tokens=1000,
    )
    from onyx.tracing.llm_utils import llm_generation_span

    with (
        trace("credential-boundary"),
        patch("onyx.tracing.llm_utils.generation_span", wraps=generation_span) as spans,
        llm_generation_span(client, LLMFlow.CHAT_RESPONSE),
    ):
        pass
    assert "api_key" not in spans.call_args.kwargs["model_config"]
    assert "custom_config" not in spans.call_args.kwargs["model_config"]
    assert "test-custom-secret" not in str(spans.call_args)
    assert "test-custom-secret" not in client.redact_error("failed test-custom-secret")
    assert "test-private-key" not in str(spans.call_args)
    assert "test-private-key" not in client.redact_error("failed with test-private-key")


def test_invoke_failure_marks_span_without_exposing_credentials() -> None:
    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key="synthetic-provider-secret",
        max_input_tokens=1000,
    )
    span = MagicMock()
    failure = TimeoutError("provider stalled: synthetic-provider-secret")
    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch.object(client, "invoke_raw", side_effect=failure),
        pytest.raises(TimeoutError) as caught,
    ):
        open_span.return_value.__enter__.return_value = span
        client.invoke(GenerationRequest(messages=[UserMessage(content="Hi")]))

    assert caught.value is failure
    span.set_error.assert_called_once_with(
        {"message": client.redact_error(f"TimeoutError: {failure}"), "data": None}
    )
    assert "synthetic-provider-secret" not in str(span.set_error.call_args)
