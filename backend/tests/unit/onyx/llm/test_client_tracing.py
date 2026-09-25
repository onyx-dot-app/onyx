"""Generation tracing at the public model client boundary."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from onyx.llm.interfaces import GenerationContext
from onyx.llm.litellm_models import (
    Choice,
    Delta,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationRequest,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import generation_span, trace
from onyx.tracing.framework.traces import TraceContentMode


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "content_mode", [TraceContentMode.FULL, TraceContentMode.METADATA_ONLY]
)
def test_generation_has_one_tagged_span(
    streaming: bool, content_mode: TraceContentMode
) -> None:
    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key=None,
        max_input_tokens=1000,
    )
    response = ModelResponse(
        id="test", created="1", choice=Choice(message=Message(content="answer"))
    )
    chunk = ModelResponseStream(
        id="test", created="1", choice=StreamingChoice(delta=Delta(content="answer"))
    )
    request = GenerationRequest(messages=[UserMessage(content="private prompt")])
    context = GenerationContext(
        flow=LLMFlow.CHAT_SESSION_NAMING, content_mode=content_mode
    )
    with (
        trace("client-tracing"),
        patch("onyx.tracing.llm_utils.generation_span", wraps=generation_span) as spans,
        patch.object(client, "invoke_raw", return_value=response),
        patch.object(client, "stream_raw", return_value=iter([chunk])),
    ):
        if streaming:
            terminal = list(client.stream(request, context))[-1]
            assert isinstance(terminal, GenerationDoneEvent)
            result = terminal.message
        else:
            result = client.invoke(request, context)
    assert result.text == "answer"
    assert spans.call_count == 1
    assert (
        spans.call_args.kwargs["model_config"]["flow"]
        == LLMFlow.CHAT_SESSION_NAMING.value
    )
    assert spans.call_args.kwargs["content_mode"] == content_mode


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


def test_stream_failure_keeps_private_exception_out_of_messages_and_trace() -> None:
    client = LitellmLLM(
        model_provider="openai",
        model_name="gpt-5-mini",
        api_key=None,
        max_input_tokens=1000,
    )
    failure = RuntimeError("synthetic-private-provider-detail")

    def chunks() -> Iterator[ModelResponseStream]:
        yield ModelResponseStream(
            id="test",
            created="1",
            choice=StreamingChoice(delta=Delta(content="Partial")),
        )
        raise failure

    events: list[GenerationEvent] = []
    with (
        patch.object(client, "stream_raw", return_value=chunks()),
        patch("onyx.llm.multi_llm.record_llm_span_output") as record,
        pytest.raises(RuntimeError) as caught,
    ):
        events.extend(
            client.stream(
                GenerationRequest(messages=[UserMessage(content="Question")]),
                GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            )
        )
    assert caught.value is failure
    terminal = events[-1]
    assert isinstance(terminal, GenerationErrorEvent)
    assert terminal.message.text == "Partial"
    assert terminal.message.error_message == "Generation failed"
    assert all(
        "synthetic-private-provider-detail" not in event.model_dump_json()
        for event in events
    )
    assert "synthetic-private-provider-detail" not in str(record.call_args)
