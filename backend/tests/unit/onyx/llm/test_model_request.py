"""Canonical one-shot requests preserve provider capabilities and cancellation."""

from collections.abc import Iterator
from contextlib import nullcontext
from typing import Any
from unittest.mock import patch

import pytest

from onyx.configs.chat_configs import LLM_INVOKE_TIMEOUT_S, LLM_SOCKET_READ_TIMEOUT
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext, LLMConfig
from onyx.llm.model_response import (
    ChatCompletionMessageToolCall,
    Choice,
    Delta,
    Message,
    ModelResponse,
    ModelResponseStream,
    ResponseFunctionCall,
    StreamingChoice,
)
from onyx.llm.models import (
    GenerationDoneEvent,
    GenerationOptions,
    GenerationRequest,
    NamedToolChoice,
    ThinkingBlock,
    ToolDefinition,
    Usage,
    UserMessage,
)
from onyx.llm.multi_llm import LitellmLLM


class RecordingProvider(LitellmLLM):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="test",
            temperature=0,
            max_input_tokens=4096,
        )

    def invoke_raw(self, prompt: Any, *args: Any, **kwargs: Any) -> ModelResponse:
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
                            function=ResponseFunctionCall(
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

    def stream_raw(
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
    result = provider.invoke(
        request, GenerationContext(stall_timeout_s=12, total_timeout_s=18.5)
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


def test_client_applies_prompt_cache_to_contiguous_prefix() -> None:
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


def test_invoke_checks_cancellation_before_provider_call() -> None:
    provider = RecordingProvider()
    signal = CancellationSignal()
    signal.cancel()
    with pytest.raises(AgentCancelled):
        provider.invoke(GenerationRequest(), GenerationContext(cancellation=signal))
    assert provider.calls == []


@pytest.mark.parametrize("total_timeout_s", [None, 18.5])
def test_invoke_deadline_is_independent_of_stream_idle_timeout(
    total_timeout_s: float | None,
) -> None:
    provider = RecordingProvider()
    context = GenerationContext(stall_timeout_s=1, total_timeout_s=total_timeout_s)
    with patch(
        "onyx.llm.multi_llm.cancellation_deadline", return_value=nullcontext()
    ) as deadline:
        provider.invoke(GenerationRequest(), context)
    expected = total_timeout_s or LLM_INVOKE_TIMEOUT_S
    assert provider.calls[0]["total_timeout_s"] == expected
    assert "stall_timeout_s" not in provider.calls[0]
    assert deadline.call_args.args[0] == expected
    assert context.total_timeout_s == total_timeout_s


@pytest.mark.parametrize("stall_timeout_s", [None, 7])
@pytest.mark.parametrize("total_timeout_s", [None, 18.5])
def test_stream_idle_timeout_does_not_create_a_total_deadline(
    stall_timeout_s: int | None, total_timeout_s: float | None
) -> None:
    provider = RecordingProvider()
    chunk = ModelResponseStream(
        id="response",
        created="1",
        choice=StreamingChoice(delta=Delta(content="answer")),
    )
    with (
        patch.object(provider, "stream_raw", return_value=iter([chunk])) as stream,
        patch(
            "onyx.llm.multi_llm.cancellation_deadline", return_value=nullcontext()
        ) as deadline,
    ):
        events = list(
            provider.stream(
                GenerationRequest(),
                GenerationContext(
                    stall_timeout_s=stall_timeout_s, total_timeout_s=total_timeout_s
                ),
            )
        )
    terminal = events[-1]
    assert isinstance(terminal, GenerationDoneEvent)
    assert terminal.message.text == "answer"
    assert stream.call_args.kwargs["stall_timeout_s"] == (
        stall_timeout_s or LLM_SOCKET_READ_TIMEOUT
    )
    if total_timeout_s is None:
        deadline.assert_not_called()
    else:
        assert deadline.call_args.args[0] == total_timeout_s


def test_tool_recovery_does_not_share_attempts_across_generations() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from onyx.llm.models import ToolChoiceOptions

    class RecoveryProvider(RecordingProvider):
        def invoke_raw(self, prompt: Any, *args: Any, **kwargs: Any) -> ModelResponse:
            response = super().invoke_raw(prompt, *args, **kwargs)
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
        results = list(executor.map(lambda _: provider.invoke(request), range(4)))
    assert len(results) == 4
    assert all(result.tool_calls[0].arguments == {"q": "term"} for result in results)


def test_interleaved_streams_isolate_cancellation_and_trace_context() -> None:
    from contextlib import closing

    from onyx.llm.cancellation import cancellation_scope, current_cancellation
    from onyx.llm.model_response import Delta, StreamingChoice
    from onyx.tracing.framework.create import trace
    from onyx.tracing.framework.scope import Scope
    from onyx.tracing.framework.spans import Span

    observed: list[tuple[CancellationSignal | None, Span[Any] | None]] = []
    closed: list[CancellationSignal | None] = []

    class StreamingProvider(RecordingProvider):
        def stream_raw(
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

    client = StreamingProvider()
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
