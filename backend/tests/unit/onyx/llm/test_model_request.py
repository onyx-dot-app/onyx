"""Canonical one-shot requests preserve provider capabilities and cancellation."""

from collections.abc import Iterator
from typing import Any

import pytest

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext, LLMConfig, LLMInfo
from onyx.llm.litellm_models import (
    ChatCompletionMessageToolCall,
    Choice,
    FunctionCall,
    Message,
    ModelResponse,
    ModelResponseStream,
)
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    NamedToolChoice,
    ThinkingBlock,
    ToolDefinition,
    Usage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM, LitellmTransport


class RecordingProvider(LitellmTransport):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def info(self) -> LLMInfo:
        return LLMInfo.model_validate(self.config.model_dump())

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test",
            temperature=0,
            max_input_tokens=4096,
        )

    def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> ModelResponse:
        assert not args
        self.calls.append({"prompt": prompt, **kwargs})
        return ModelResponse(
            id="test",
            created="1",
            choice=Choice(
                finish_reason="tool_calls",
                message=Message(
                    content="answer",
                    reasoning_content="reasoning",
                    thinking_blocks=[
                        ThinkingBlock(thinking="signed", signature="proof")
                    ],
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id="call",
                            function=FunctionCall(
                                name="lookup", arguments='{"q":"term"}'
                            ),
                        )
                    ],
                ),
            ),
            usage=Usage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=2,
            ),
        )

    def stream(
        self, prompt: Any, *args: Any, **kwargs: Any
    ) -> Iterator[ModelResponseStream]:
        del prompt, args, kwargs
        raise AssertionError("invoke must retain the provider's nonstreaming API")


def test_invoke_preserves_options_and_returns_canonical_content() -> None:
    provider = RecordingProvider()
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
    result = LitellmLLM(provider).invoke(
        request, GenerationContext(timeout=12, total_timeout=18.5)
    )
    assert result.text == "answer"
    assert result.thinking == "reasoning"
    assert result.thinking_blocks == [
        ThinkingBlock(thinking="signed", signature="proof")
    ]
    assert result.tool_calls[0].arguments == {"q": "term"}
    assert result.stop_reason == "tool_calls"
    assert result.usage is not None and result.usage.cache_read_input_tokens == 2
    options = provider.calls[0]
    assert options["structured_response_format"] == {"type": "json_object"}
    assert options["tool_choice"] == request.options.tool_choice
    assert options["total_timeout_s"] == 18.5
    assert options["max_tokens"] == 42
    assert [message.content for message in options["prompt"]] == [
        "instructions",
        "question",
    ]


def test_invoke_checks_cancellation_before_provider_call() -> None:
    provider = RecordingProvider()
    signal = CancellationSignal()
    signal.cancel()
    with pytest.raises(AgentCancelled):
        LitellmLLM(provider).invoke(
            GenerationRequest(), GenerationContext(cancellation=signal)
        )
    assert provider.calls == []


def test_tool_recovery_does_not_share_attempts_across_generations() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from onyx.llm.models import ToolChoiceOptions

    class RecoveryProvider(RecordingProvider):
        def invoke(self, prompt: Any, *args: Any, **kwargs: Any) -> ModelResponse:
            response = super().invoke(prompt, *args, **kwargs)
            response.choice.message.tool_calls = []
            response.choice.message.content = (
                '{"name":"lookup","arguments":{"q":"term"}}'
            )
            return response

    provider = RecoveryProvider()
    request = GenerationRequest(
        tools=[ToolDefinition(name="lookup", description="", parameters={})],
        options=GenerationOptions(tool_choice=ToolChoiceOptions.REQUIRED),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: LitellmLLM(provider).invoke(request), range(4))
        )
    assert len(results) == 4
    assert all(result.tool_calls[0].arguments == {"q": "term"} for result in results)


def test_interleaved_streams_isolate_cancellation_and_trace_context() -> None:
    from contextlib import closing

    from onyx.llm.cancellation import cancellation_scope, current_cancellation
    from onyx.llm.litellm_models import Delta, StreamingChoice
    from onyx.tracing.framework.create import trace
    from onyx.tracing.framework.scope import Scope
    from onyx.tracing.framework.spans import Span

    observed: list[tuple[CancellationSignal | None, Span[Any] | None]] = []
    closed: list[CancellationSignal | None] = []

    class StreamingProvider(RecordingProvider):
        def stream(
            self, prompt: Any, *args: Any, **kwargs: Any
        ) -> Iterator[ModelResponseStream]:
            del prompt, args, kwargs
            observed.append((current_cancellation(), Scope.get_current_span()))
            try:
                yield ModelResponseStream(
                    id="test",
                    created="1",
                    choice=StreamingChoice(delta=Delta(content="answer")),
                )
            finally:
                closed.append(current_cancellation())

    client = LitellmLLM(StreamingProvider())
    caller_signal, first_signal, second_signal = (
        CancellationSignal() for _ in range(3)
    )
    with cancellation_scope(caller_signal), trace("stream isolation"):
        caller_span = Scope.get_current_span()
        caller_trace = Scope.get_current_trace()

        def assert_caller_context() -> None:
            assert current_cancellation() is caller_signal
            assert Scope.get_current_span() is caller_span
            assert Scope.get_current_trace() is caller_trace

        with (
            closing(
                client.stream(
                    GenerationRequest(), GenerationContext(cancellation=first_signal)
                )
            ) as first,
            closing(
                client.stream(
                    GenerationRequest(), GenerationContext(cancellation=second_signal)
                )
            ) as second,
        ):
            assert next(first).type == "start"
            assert_caller_context()
            assert next(second).type == "start"
            assert_caller_context()
            next(first)
            next(second)
            assert_caller_context()
            assert [signal for signal, _ in observed] == [first_signal, second_signal]
            assert observed[0][1] is not None and observed[0][1] is not observed[1][1]
            first.close()
            assert_caller_context()
            remaining = list(second)
            assert remaining[-1].type == "done"
            assert_caller_context()
        assert closed == [first_signal, second_signal]
        assert_caller_context()
