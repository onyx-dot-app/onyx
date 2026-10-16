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


def test_redact_error_covers_custom_config_mapped_api_key() -> None:
    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key=None,
        custom_config={"OPENAIAPIKEY": "mapped-provider-secret"},
        max_input_tokens=1000,
    )
    assert "mapped-provider-secret" not in client.redact_error(
        "failed with mapped-provider-secret"
    )


@pytest.mark.parametrize("has_response", [False, True])
@pytest.mark.parametrize("metadata_only", [False, True])
def test_cancelled_invoke_records_error_and_available_usage(
    has_response: bool, metadata_only: bool
) -> None:
    from onyx.llm.cancellation import AgentCancelled, CancellationSignal
    from onyx.llm.interfaces import GenerationContext
    from onyx.llm.model_response import Choice, Message, ModelResponse
    from onyx.llm.models import Usage
    from onyx.tracing.framework.span_data import GenerationSpanData
    from onyx.tracing.framework.traces import TraceContentMode

    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key="test",
        max_input_tokens=1000,
    )
    signal = CancellationSignal()
    response = ModelResponse(
        id="response",
        created="1",
        choice=Choice(message=Message(content="completed answer")),
        usage=Usage(
            prompt_tokens=10,
            completion_tokens=3,
            total_tokens=13,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
    )
    span = MagicMock()
    span.span_data = GenerationSpanData()
    span.content_mode = (
        TraceContentMode.METADATA_ONLY if metadata_only else TraceContentMode.FULL
    )

    def invoke(*_args: object, **_kwargs: object) -> ModelResponse:
        signal.cancel()
        if not has_response:
            signal.check()
        return response

    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch.object(client, "invoke_raw", side_effect=invoke),
        pytest.raises(AgentCancelled),
    ):
        open_span.return_value.__enter__.return_value = span
        client.invoke(GenerationRequest(), GenerationContext(cancellation=signal))

    span.set_error.assert_called_once_with(
        {"message": "AgentCancelled: ", "data": None}
    )
    if has_response:
        assert span.span_data.usage is not None
        assert span.span_data.usage["input_tokens"] == 10
        assert span.span_data.usage["output_tokens"] == 3
    else:
        assert span.span_data.usage is None
    expected_output = [{"role": "assistant", "content": "completed answer"}]
    assert span.span_data.output == (
        expected_output if has_response and not metadata_only else None
    )


@pytest.mark.parametrize("streaming", [False, True])
def test_cancellation_when_span_opens_is_recorded(streaming: bool) -> None:
    from onyx.llm.cancellation import AgentCancelled, CancellationSignal
    from onyx.llm.interfaces import GenerationContext

    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key="test",
        max_input_tokens=1000,
    )
    signal = CancellationSignal()
    span = MagicMock()

    def enter() -> MagicMock:
        signal.cancel()
        return span

    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch.object(client, "invoke_raw") as invoke,
        patch.object(client, "stream_raw") as stream,
        pytest.raises(AgentCancelled),
    ):
        open_span.return_value.__enter__.side_effect = enter
        context = GenerationContext(cancellation=signal)
        if streaming:
            list(client.stream(GenerationRequest(), context))
        else:
            client.invoke(GenerationRequest(), context)

    invoke.assert_not_called()
    stream.assert_not_called()
    span.set_error.assert_called_once_with(
        {"message": "AgentCancelled: ", "data": None}
    )
