"""Generation tracing at the public model client boundary."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.chat import prompt_formatting
from onyx.chat.prompt_formatting import PromptMetadata, prepare_model_messages
from onyx.file_store.models import ChatFileType, ChatLoadedFile
from onyx.llm import model_request
from onyx.llm.interfaces import GenerationContext
from onyx.llm.model_response import (
    Choice,
    Delta,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationRequest,
    ImageContentPart,
    ImageUrlDetail,
    ThinkingContent,
    ToolCall,
    Usage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import generation_span, trace
from onyx.tracing.framework.traces import TraceContentMode
from tests.unit.onyx.agents.fakes import collect_generation


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
            events = list(client.stream(request, context))
            terminal = events[-1]
            assert isinstance(terminal, GenerationDoneEvent)
            result = collect_generation(events)
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
    usage = Usage(
        prompt_tokens=3,
        completion_tokens=1,
        total_tokens=4,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    def chunks() -> Iterator[ModelResponseStream]:
        yield ModelResponseStream(
            id="test",
            created="1",
            choice=StreamingChoice(delta=Delta(content="Partial")),
            usage=usage,
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
    assert collect_generation(events).text == "Partial"
    assert terminal.error_message == "Generation failed"
    assert terminal.usage == usage
    assert collect_generation(events).usage == usage
    assert all(
        "synthetic-private-provider-detail" not in event.model_dump_json()
        for event in events
    )
    assert "synthetic-private-provider-detail" not in str(record.call_args)


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


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("cache_enabled", [False, True])
@pytest.mark.parametrize("supports_images", [False, True])
@pytest.mark.parametrize("with_tokenizer", [False, True])
@pytest.mark.parametrize("use_client_capability", [False, True])
def test_cache_trace_uses_prepared_image_decisions(
    monkeypatch: pytest.MonkeyPatch,
    streaming: bool,
    cache_enabled: bool,
    supports_images: bool,
    with_tokenizer: bool,
    use_client_capability: bool,
) -> None:
    client = LitellmLLM(
        api_key=None,
        model_provider="azure",
        model_name="unknown-model",
        max_input_tokens=1000,
        supports_images=supports_images if use_client_capability else None,
    )
    monkeypatch.setattr(prompt_formatting, "PROMPT_CACHE_CHAT_HISTORY", cache_enabled)
    monkeypatch.setattr(model_request, "PROMPT_CACHE_CHAT_HISTORY", cache_enabled)
    monkeypatch.setattr(prompt_formatting, "ENABLE_AZURE_IMAGE_CAP", True)
    monkeypatch.setattr(prompt_formatting, "_AZURE_DEFAULT_IMAGE_CAP", 1)
    capability = MagicMock(
        return_value=not supports_images if use_client_capability else supports_images
    )
    selector = MagicMock(wraps=prompt_formatting._select_recent_image_indices)
    monkeypatch.setattr(prompt_formatting, "model_supports_image_input", capability)
    monkeypatch.setattr(prompt_formatting, "_select_recent_image_indices", selector)
    monkeypatch.setattr(
        prompt_formatting, "get_image_type_from_bytes", lambda _: "image/png"
    )
    source = UserMessage(
        content="describe",
        metadata=PromptMetadata(
            token_count=105,
            image_token_count=100,
            should_cache=True,
            image_files=[
                ChatLoadedFile(
                    file_id=str(index),
                    file_type=ChatFileType.IMAGE,
                    content=b"image",
                    content_text=None,
                    token_count=50,
                )
                for index in range(2)
            ],
        ),
    )
    messages = prepare_model_messages(
        [source],
        client.config,
        token_counter=(lambda _: 5) if with_tokenizer else None,
    )
    request = GenerationRequest(messages=messages)
    response = ModelResponse(
        id="test", created="1", choice=Choice(message=Message(content="done"))
    )
    chunk = ModelResponseStream(
        id="test", created="1", choice=StreamingChoice(delta=Delta(content="done"))
    )
    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch.object(client, "invoke_raw", return_value=response) as invoke,
        patch.object(client, "stream_raw", return_value=iter([chunk])) as stream,
    ):
        span = open_span.return_value.__enter__.return_value
        span.span_data.model_config = {"flow": "chat_response"}
        if streaming:
            list(client.stream(request))
        else:
            client.invoke(request)
        sent = (stream if streaming else invoke).call_args.args[0]
    if use_client_capability:
        capability.assert_not_called()
    else:
        capability.assert_called_once_with("unknown-model", "azure", None)
    assert selector.call_count == int(supports_images)
    stats = span.span_data.model_config
    assert stats["flow"] == "chat_response"
    assert stats["prompt_cache_chat_history"] == ("on" if cache_enabled else "off")
    assert stats["cacheable_prefix_msgs"] == ("1" if cache_enabled else "0")
    marker_tokens = 15 if with_tokenizer else 85
    assert stats["cacheable_prefix_tokens"] == str(
        (55 if supports_images else marker_tokens) if cache_enabled else 0
    )
    assert stats["history_msgs"] == str(len(sent))
    assert sum(isinstance(part, ImageContentPart) for part in sent[0].content) == int(
        supports_images
    )
    assert "estimated_tokens" not in request.model_dump_json()


@pytest.mark.parametrize(
    "message",
    [
        UserMessage(
            content=[
                ImageContentPart(
                    image_url=ImageUrlDetail(url="https://example.com/image.png")
                )
            ]
        ),
        AssistantMessage(
            content=[ToolCall(id="call", name="search", arguments={"query": "hello"})]
        ),
        AssistantMessage(content=[ThinkingContent(text="Reasoning")]),
    ],
    ids=["image", "tool-call", "reasoning"],
)
def test_cache_trace_omits_incomplete_token_estimates(
    message: UserMessage | AssistantMessage,
) -> None:
    request = GenerationRequest(messages=[UserMessage(content="text"), message])
    stats = model_request.cache_split_stats(request, 2)
    assert "cacheable_prefix_tokens" not in stats
    assert stats["cacheable_prefix_msgs"] == "2"
    assert stats["history_msgs"] == "2"

    # Unknown costs outside the cached prefix must not hide a complete estimate.
    assert model_request.cache_split_stats(request, 1)["cacheable_prefix_tokens"] == "1"
    assert model_request.cache_split_stats(request, 0)["cacheable_prefix_tokens"] == "0"

    request.messages[1] = message.model_copy(update={"estimated_tokens": 50})
    assert (
        model_request.cache_split_stats(request, 2)["cacheable_prefix_tokens"] == "51"
    )
