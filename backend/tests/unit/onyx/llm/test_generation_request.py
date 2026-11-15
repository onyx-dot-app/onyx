"""Shared-message requests map onto the provider API and back without losing data."""

import json
from collections.abc import Iterator
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
    Delta,
    Message,
    ModelResponse,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
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
    def __init__(
        self, response: ModelResponse | None = None, *, config: LLMConfig | None = None
    ) -> None:
        self._config = config or _config()
        self.calls: list[dict[str, Any]] = []
        self._response = response or _response(Message(content="answer"))
        self._model_kwargs: dict[str, Any] = {}

    @property
    def config(self) -> LLMConfig:
        return self._config

    def invoke_raw(self, prompt: Any, *args: Any, **kwargs: Any) -> ModelResponse:
        assert not args
        self.calls.append({"prompt": prompt, **kwargs})
        return self._response

    def stream_raw(
        self, prompt: Any, *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        assert not args
        self.calls.append({"prompt": prompt, **kwargs})
        yield ModelResponseStream(
            id="stream",
            created="1",
            choice=StreamingChoice(delta=Delta(content="answer"), finish_reason="stop"),
        )


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "model_name,deployment_name,allowed,choice,expected_names,expected_choice",
    [
        ("ordinary", None, None, "auto", ["lookup", "other"], "auto"),
        ("claude-sonnet-4-5", None, None, "lookup", ["lookup"], "auto"),
        ("qwen3", None, None, "lookup", ["lookup"], "auto"),
        ("alias", "glm-5", None, "lookup", ["lookup"], "auto"),
        (
            "ordinary",
            None,
            frozenset({"lookup"}),
            "required",
            ["lookup", "other"],
            "lookup",
        ),
        (
            "claude-sonnet-4-5",
            None,
            frozenset({"lookup"}),
            "required",
            ["lookup"],
            "auto",
        ),
        ("qwen3", None, frozenset({"lookup"}), "required", ["lookup"], "auto"),
        ("alias", "glm-5", frozenset({"lookup"}), "required", ["lookup"], "auto"),
        (
            "ordinary",
            None,
            frozenset({"lookup", "other"}),
            "required",
            ["lookup", "other"],
            "required",
        ),
        ("ordinary", None, None, "required", ["lookup", "other"], "required"),
        ("ordinary", None, frozenset(), "none", ["lookup", "other"], "none"),
        ("claude-sonnet-4-5", None, frozenset(), "none", ["lookup", "other"], "none"),
        ("qwen3", None, frozenset(), "none", [], "none"),
        ("alias", "glm-5", frozenset(), "none", [], "none"),
        ("ordinary", None, frozenset({"other"}), "auto", ["lookup", "other"], "auto"),
    ],
)
def test_tool_permissions_preserve_declared_tools_and_semantic_options(
    stream: bool,
    model_name: str,
    deployment_name: str | None,
    allowed: frozenset[str] | None,
    choice: str,
    expected_names: list[str],
    expected_choice: str,
) -> None:
    provider = RecordingProvider(
        config=_config(model_name=model_name).model_copy(
            update={"deployment_name": deployment_name}
        )
    )
    request = GenerationRequest(
        messages=[UserMessage(content="question")],
        tools=[
            ToolDefinition(name=name, description=name, parameters={})
            for name in ["lookup", "other"]
        ],
        allowed_tool_names=allowed,
        options=GenerationOptions(
            tool_choice=NamedToolChoice(name="lookup")
            if choice == "lookup"
            else ToolChoiceOptions(choice)
        ),
    )
    original = request.model_dump_json()
    if stream:
        list(provider.stream(request))
    else:
        provider.invoke(request)
    (call,) = provider.calls
    assert [tool["function"]["name"] for tool in call["tools"] or []] == expected_names
    assert call["tool_choice"] == (
        NamedToolChoice(name=expected_choice)
        if expected_choice == "lookup"
        else ToolChoiceOptions(expected_choice)
    )
    assert request.model_dump_json() == original


@pytest.mark.parametrize(
    "allowed,choice,error",
    [
        (frozenset({"unknown"}), ToolChoiceOptions.AUTO, "not declared"),
        (None, NamedToolChoice(name="unknown"), "not declared"),
        (frozenset(), ToolChoiceOptions.REQUIRED, "needs an allowed tool"),
        (frozenset(), NamedToolChoice(name="lookup"), "not allowed"),
    ],
)
def test_invalid_tool_permissions_fail_before_provider_call(
    allowed: frozenset[str] | None,
    choice: ToolChoiceOptions | NamedToolChoice,
    error: str,
) -> None:
    provider = RecordingProvider()
    request = GenerationRequest(
        tools=[ToolDefinition(name="lookup", description="", parameters={})],
        allowed_tool_names=allowed,
        options=GenerationOptions(tool_choice=choice),
    )
    with pytest.raises(ValueError, match=error):
        provider.invoke(request)
    assert provider.calls == []


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
                "strict": False,
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


@pytest.mark.parametrize(
    "model_provider,model_name,expected_system_contents",
    [
        ("hosted_vllm", "Pro", ["shared head\n\nuser info"]),
        ("openai", "gpt-4o", ["shared head\n\nuser info"]),
        ("anthropic", "claude-sonnet-4-5", ["shared head", "user info"]),
    ],
)
def test_invoke_merges_leading_system_messages_unless_cached_separately(
    model_provider: str, model_name: str, expected_system_contents: list[str]
) -> None:
    provider = RecordingProvider(config=_config(model_provider, model_name))
    request = GenerationRequest(
        system_prompt="shared head",
        messages=[
            SystemMessage(content="user info", cacheable=True),
            UserMessage(content="question"),
        ],
    )
    provider.invoke(request)

    prompt = provider.calls[0]["prompt"]
    system_messages = [m for m in prompt if isinstance(m, ProviderSystemMessage)]
    assert [m.content for m in system_messages] == expected_system_contents
    assert prompt[: len(system_messages)] == system_messages
    assert isinstance(prompt[-1], ProviderUserMessage)
    assert prompt[-1].content == "question"


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
    assert message.thinking_blocks is not None
    thinking = message.thinking_blocks[0]
    assert isinstance(thinking, ThinkingBlock)
    thinking.signature = "changed-signature"
    assert response.choice.message.thinking_blocks == [signed]
    assert signed.signature == "provider-signature"


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


@pytest.mark.parametrize(
    "choice", [ToolChoiceOptions.REQUIRED, NamedToolChoice(name="search")]
)
def test_tool_recovery_keeps_answer_text_and_signed_thinking(
    choice: ToolChoiceOptions | NamedToolChoice,
) -> None:
    signed = ThinkingBlock(thinking="plan", signature="provider-signature")
    payload = '{"name": "search", "arguments": {"query": "onyx"}}'
    request = GenerationRequest(
        tools=[ToolDefinition(name="search", description="Search", parameters={})],
        options=GenerationOptions(tool_choice=choice),
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


@pytest.mark.parametrize(
    "allowed", [frozenset(), frozenset({"other"}), frozenset({"search"})]
)
def test_recovered_explicit_call_preserves_name_for_runtime_permissions(
    allowed: frozenset[str],
) -> None:
    text = '<function_calls><invoke name="search"></invoke></function_calls>'
    request = GenerationRequest(
        tools=[
            ToolDefinition(name=name, description="", parameters={})
            for name in ("search", "other")
        ],
        allowed_tool_names=allowed,
    )
    message = recover_tool_calls(
        AssistantMessage(content=[TextContent(text=text)]), request
    )
    assert [call.name for call in message.tool_calls] == (["search"] if allowed else [])
    if not allowed:
        assert message.text == text


def test_bare_argument_recovery_uses_allowed_tools_without_changing_semantic_choice() -> (
    None
):
    provider = RecordingProvider(
        _response(Message(content='{"query":"Onyx"}')),
        config=_config(model_name="claude-sonnet-4-5"),
    )
    request = GenerationRequest(
        tools=[
            ToolDefinition(
                name=name,
                description="",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            )
            for name in ("search", "other")
        ],
        allowed_tool_names=frozenset({"search"}),
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    message = provider.invoke(request)
    assert provider.calls[0]["tool_choice"] == ToolChoiceOptions.AUTO
    assert request.options.tool_choice == ToolChoiceOptions.REQUIRED
    assert [call.name for call in message.tool_calls] == ["search"]
