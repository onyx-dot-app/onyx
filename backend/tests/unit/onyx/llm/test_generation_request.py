"""Shared-message requests map onto the provider API and back without losing data."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, JsonValue

from onyx.configs.chat_configs import LLM_INVOKE_TIMEOUT_S
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import GenerationContext, LLMConfig
from onyx.llm.model_request import (
    CODE_BLOCK_MARKDOWN,
    serialize_request,
)
from onyx.llm.model_request import AssistantMessage as ProviderAssistantMessage
from onyx.llm.model_request import SystemMessage as ProviderSystemMessage
from onyx.llm.model_request import UserMessage as ProviderUserMessage
from onyx.llm.model_response import (
    ChatCompletionMessageToolCall,
    Choice,
    Message,
    ModelResponse,
    ResponseFunctionCall,
    recover_tool_calls,
    to_assistant_message,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    NamedToolChoice,
    SystemMessage,
    TextContent,
    ThinkingBlock,
    ToolCall,
    ToolChoiceOptions,
    ToolDefinition,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM
from onyx.tracing.flows import LLMFlow


def _config(model_provider: str = "openai", model_name: str = "test") -> LLMConfig:
    return LLMConfig(
        model_provider=model_provider,
        model_name=model_name,
        temperature=0,
        max_input_tokens=4096,
    )


def _response(message: Message, finish_reason: str | None = "stop") -> ModelResponse:
    return ModelResponse(
        id="test",
        created="1",
        choice=Choice(finish_reason=finish_reason, message=message),
    )


class RecordingProvider(LitellmLLM):
    def __init__(self, response: ModelResponse | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response or _response(Message(content="answer"))

    @property
    def config(self) -> LLMConfig:
        return _config()

    def invoke_raw(self, prompt: Any, *args: Any, **kwargs: Any) -> ModelResponse:
        assert not args
        self.calls.append({"prompt": prompt, **kwargs})
        return self._response


def test_invoke_preserves_options_and_returns_shared_content() -> None:
    provider = RecordingProvider(
        _response(
            Message(
                content="answer",
                reasoning_content="reasoning",
                thinking_blocks=[ThinkingBlock(thinking="signed", signature="proof")],
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call",
                        function=ResponseFunctionCall(
                            name="lookup", arguments='{"q":"term"}'
                        ),
                    )
                ],
            ),
            finish_reason="tool_calls",
        )
    )
    provider._response.usage = Usage(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=2,
    )
    request = GenerationRequest(
        messages=[UserMessage(content="question")],
        system_prompt="instructions",
        tools=[ToolDefinition(name="lookup", description="Find facts", parameters={})],
        options=GenerationOptions(
            tool_choice=NamedToolChoice(name="lookup"),
            structured_response_format={"type": "json_object"},
            max_tokens=42,
        ),
    )

    result = provider.invoke(request, GenerationContext(total_timeout_s=18.5))

    assert result.text == "answer"
    assert result.thinking == "reasoning"
    assert result.thinking_blocks == [
        ThinkingBlock(thinking="signed", signature="proof")
    ]
    assert result.tool_calls[0].arguments == {"q": "term"}
    assert result.stop_reason == "tool_calls"
    assert result.usage is not None and result.usage.cache_read_input_tokens == 2
    call = provider.calls[0]
    assert call["structured_response_format"] == {"type": "json_object"}
    assert call["tool_choice"] == request.options.tool_choice
    assert call["total_timeout_s"] == 18.5
    assert call["max_tokens"] == 42
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Find facts",
                "parameters": {},
            },
        }
    ]
    assert [message.content for message in call["prompt"]] == [
        "instructions",
        "question",
    ]


def test_invoke_defaults_timeout_omits_empty_tools_and_tags_its_span() -> None:
    provider = RecordingProvider()
    request = GenerationRequest(messages=[UserMessage(content="question")])

    with patch("onyx.llm.multi_llm.llm_generation_span") as span:
        provider.invoke(request)
        provider.invoke(request, GenerationContext(flow=LLMFlow.MEMORY_UPDATE))

    assert provider.calls[0]["total_timeout_s"] == LLM_INVOKE_TIMEOUT_S
    assert provider.calls[0]["tools"] is None
    flows = [call.args[1] for call in span.call_args_list]
    assert flows == [LLMFlow.UNTAGGED_INVOKE, LLMFlow.MEMORY_UPDATE]


def test_invoke_applies_prompt_cache_to_contiguous_prefix() -> None:
    provider = RecordingProvider()
    request = GenerationRequest(
        system_prompt="instructions",
        messages=[
            UserMessage(content="cached context", cacheable=True),
            UserMessage(content="question"),
            UserMessage(content="later context", cacheable=True),
        ],
    )
    with patch(
        "onyx.llm.multi_llm.process_with_prompt_cache", return_value=([], None)
    ) as prepare_cache:
        provider.invoke(request)

    prepare_cache.assert_called_once()
    args = prepare_cache.call_args.kwargs
    assert [message.content for message in args["cacheable_prefix"]] == [
        "instructions",
        "cached context",
    ]
    assert [message.content for message in args["suffix"]] == [
        "question",
        "later context",
    ]
    assert args["continuation"] is False
    assert args["with_metadata"] is False
    assert provider.calls[0]["prompt"] == []


def test_invoke_skips_prompt_cache_without_a_cacheable_prefix() -> None:
    provider = RecordingProvider()
    with patch("onyx.llm.multi_llm.process_with_prompt_cache") as prepare_cache:
        provider.invoke(GenerationRequest(messages=[UserMessage(content="question")]))

    prepare_cache.assert_not_called()


def test_serialize_request_reenables_formatting_for_openai_reasoning_models() -> None:
    request = GenerationRequest(
        messages=[
            SystemMessage(content="first"),
            SystemMessage(content="second"),
            UserMessage(content="question"),
        ]
    )

    messages, cacheable_prefix = serialize_request(request, _config(model_name="gpt-5"))

    assert cacheable_prefix == 0
    assert messages[0] == ProviderSystemMessage(content=CODE_BLOCK_MARKDOWN + "first")
    assert messages[1] == ProviderSystemMessage(content="second")
    unchanged, _ = serialize_request(request, _config(model_name="gpt-4o"))
    assert unchanged[0] == ProviderSystemMessage(content="first")


def test_serialize_request_flattens_tool_history_for_ollama() -> None:
    request = GenerationRequest(
        messages=[
            AssistantMessage(
                content=[
                    TextContent(text="Looking."),
                    ToolCall(id="call-1", name="search", arguments={"q": "x"}),
                ]
            ),
            ToolResultMessage(content="found", tool_call_id="call-1", tool_name="x"),
        ]
    )

    messages, _ = serialize_request(
        request, _config(model_provider=LlmProviderNames.OLLAMA_CHAT)
    )

    assert messages == [
        ProviderAssistantMessage(
            content='Looking.\n[Tool Call] name=search id=call-1 args={"q": "x"}'
        ),
        ProviderUserMessage(content="[Tool Result] id=call-1\nfound"),
    ]


class StructuredToolArguments(BaseModel):
    queries: list[str]
    filters: dict[str, str]
    literal: str


@pytest.mark.parametrize("text_fallback", [False, True])
def test_to_assistant_message_normalizes_schema_directed_tool_arguments(
    text_fallback: bool,
) -> None:
    arguments = {
        "queries": '["first", "second"]',
        "filters": '{"source": "docs"}',
        "literal": '["keep this as text"]',
    }
    encoded = json.dumps(json.dumps(arguments))
    payload = json.dumps({"name": "search", "arguments": arguments})
    request = GenerationRequest(
        messages=[UserMessage(content="Search")],
        tools=[
            ToolDefinition(
                name="search",
                description="Search sources",
                parameters=StructuredToolArguments.model_json_schema(),
            )
        ],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    response = _response(
        Message(
            content=payload if text_fallback else None,
            tool_calls=None
            if text_fallback
            else [
                ChatCompletionMessageToolCall(
                    id="search-call",
                    function=ResponseFunctionCall(name="search", arguments=encoded),
                )
            ],
        )
    )

    message = to_assistant_message(response, request)

    call = message.tool_calls[0]
    assert call.arguments_complete
    assert call.argument_error is None
    parsed = StructuredToolArguments.model_validate(call.arguments)
    assert parsed.queries == ["first", "second"]
    assert parsed.filters == {"source": "docs"}
    assert parsed.literal == arguments["literal"]


@pytest.mark.parametrize("prefix", ["Before ", ""])
def test_xml_tool_recovery_preserves_visible_prose(prefix: str) -> None:
    text = (
        prefix
        + '<function_calls><invoke name="search">'
        + '<parameter name="queries" string="false">["Onyx"]</parameter>'
        + "</invoke></function_calls>"
        + "  "
        + "\nAfter"
    )
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
    )

    message = recover_tool_calls(
        AssistantMessage(content=[TextContent(text=text)]), request
    )

    assert message.text == prefix + "\nAfter"
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].name == "search"
    assert message.tool_calls[0].arguments == {"queries": ["Onyx"]}


def test_tool_recovery_is_off_without_tools() -> None:
    response = _response(Message(content='{"name":"search","arguments":{}}'))

    message = to_assistant_message(
        response, GenerationRequest(messages=[UserMessage(content="Hi")])
    )

    assert message.tool_calls == []
    assert message.text == '{"name":"search","arguments":{}}'


@pytest.mark.parametrize(
    "arguments, expected, valid",
    [
        ("", {}, True),
        ('{"query":"term"}', {"query": "term"}, True),
        (json.dumps('{"query":"term"}'), {"query": "term"}, True),
        ('{"query":broken', {}, False),
        ("[]", {}, False),
    ],
)
def test_complete_conversion_preserves_native_calls_and_response_metadata(
    arguments: str, expected: dict[str, JsonValue], valid: bool
) -> None:
    signed = ThinkingBlock(thinking="plan", signature="provider-signature")
    usage = Usage(
        prompt_tokens=10,
        completion_tokens=3,
        total_tokens=13,
        cache_creation_input_tokens=1,
        cache_read_input_tokens=2,
    )
    fallback = '{"name":"search","arguments":{"query":"fallback"}}'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    response = _response(
        Message(
            content=fallback,
            reasoning_content="plan",
            thinking_blocks=[signed],
            tool_calls=[
                ChatCompletionMessageToolCall(
                    id="native-call",
                    function=ResponseFunctionCall(name="search", arguments=arguments),
                )
            ],
        ),
        finish_reason="tool_calls",
    )
    response.usage = usage

    message = to_assistant_message(response, request)

    assert message.text == fallback
    assert message.thinking == "plan"
    assert message.thinking_blocks == [signed]
    assert message.usage == usage
    assert message.stop_reason == "tool_calls"
    assert len(message.tool_calls) == 1
    call = message.tool_calls[0]
    assert call.id == "native-call"
    assert call.arguments == expected
    assert call.arguments_complete is valid
    assert (call.argument_error is None) is valid
    assert call.raw_arguments == (None if valid else arguments)
    # The result must not alias the provider response.
    assert message.usage is not None
    message.usage.prompt_tokens = 999
    assert response.usage is not None and response.usage.prompt_tokens == 10


def test_invoke_records_the_provider_response_on_its_span() -> None:
    provider = RecordingProvider()
    span = MagicMock()
    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch("onyx.llm.multi_llm.record_llm_response") as record,
    ):
        open_span.return_value.__enter__.return_value = span
        provider.invoke(GenerationRequest(messages=[UserMessage(content="Hi")]))

    record.assert_called_once_with(span, provider._response)


def test_invoke_records_provider_failures_on_its_span() -> None:
    provider = RecordingProvider()
    span = MagicMock()
    failure = TimeoutError("provider stalled")
    with (
        patch("onyx.llm.multi_llm.llm_generation_span") as open_span,
        patch.object(provider, "invoke_raw", side_effect=failure),
        pytest.raises(TimeoutError),
    ):
        open_span.return_value.__enter__.return_value = span
        provider.invoke(GenerationRequest(messages=[UserMessage(content="Hi")]))

    span.set_error.assert_called_once_with(
        {"message": "TimeoutError: provider stalled", "data": None}
    )


def test_tool_recovery_keeps_answer_text_and_signed_thinking() -> None:
    signed = ThinkingBlock(thinking="plan", signature="provider-signature")
    payload = '{"name": "search", "arguments": {"query": "onyx"}}'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    response = _response(
        Message(
            content=f"Searching now. {payload}",
            reasoning_content="plan",
            thinking_blocks=[signed],
        )
    )

    message = to_assistant_message(response, request)

    assert message.text == f"Searching now. {payload}"
    assert message.thinking == "plan"
    assert message.thinking_blocks == [signed]
    assert [call.name for call in message.tool_calls] == ["search"]
    assert message.tool_calls[0].arguments == {"query": "onyx"}
