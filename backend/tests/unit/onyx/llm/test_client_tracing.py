"""Generation tracing at the public model client boundary."""

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
from onyx.llm.models import GenerationRequest, UserMessage
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport
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
        LitellmTransport(
            model_provider="openai",
            model_name="gpt-5-mini",
            api_key=None,
            max_input_tokens=1000,
        )
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
        patch.object(client.transport, "invoke", return_value=response),
        patch.object(client.transport, "stream", return_value=iter([chunk])),
    ):
        if streaming:
            result = list(client.stream(request, context))[-1].message
        else:
            result = client.invoke(request, context)
    assert result.text == "answer"
    assert spans.call_count == 1
    assert (
        spans.call_args.kwargs["model_config"]["flow"]
        == LLMFlow.CHAT_SESSION_NAMING.value
    )
    assert spans.call_args.kwargs["content_mode"] == content_mode


def test_model_information_excludes_credentials() -> None:
    client = LitellmLLM(
        LitellmTransport(
            model_provider="openai",
            model_name="gpt-5-mini",
            api_key="test-private-key",
            max_input_tokens=1000,
        )
    )
    assert "api_key" not in client.info.model_dump()
    assert "test-private-key" not in client.info.model_dump_json()
    assert "test-private-key" not in client.redact_error("failed with test-private-key")
