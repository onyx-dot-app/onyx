# ruff: noqa: ARG002
"""Unit tests for `onyx.llm.tracing_wrap`.

Cover:
- `LLM.__init_subclass__` auto-wraps `invoke` and `stream` on concrete subclasses
- Wrapper is idempotent (double-application is a no-op)
- Outer-span guard (``_outer_generation_span_active``) skips fallback when
  an outer ``generation_span`` is active
- Stale-span guard: a finished ``GenerationSpanData`` in the contextvar does
  not suppress fallback tracing (regression guard for the ``GeneratorExit``
  corner case)
- `_extract_prompt` helper reads positional and keyword arguments

The `_FakeLLM` test double's `invoke` / `stream` signatures intentionally
mirror the `LLM` abstract interface, which means many parameters are
declared but unused — hence the `ARG002` suppression at the file level.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from typing import Any
from typing import cast
from unittest.mock import patch

import pytest

from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Choice
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall as DeltaFunctionCall
from onyx.llm.model_response import Message
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import StreamingChoice
from onyx.llm.model_response import Usage
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.models import UserMessage
from onyx.llm.tracing_wrap import _ALREADY_WRAPPED_ATTR
from onyx.llm.tracing_wrap import _extract_prompt
from onyx.llm.tracing_wrap import _finalize_tool_calls
from onyx.llm.tracing_wrap import _merge_tool_call_delta
from onyx.llm.tracing_wrap import _outer_generation_span_active
from onyx.llm.tracing_wrap import _validate_prompt_param
from onyx.llm.tracing_wrap import wrap_invoke
from onyx.llm.tracing_wrap import wrap_stream
from onyx.tracing.framework.create import generation_span
from onyx.tracing.framework.create import trace

_TEST_MODEL_RESPONSE = ModelResponse(
    id="test-id",
    created="2026-04-22T00:00:00Z",
    choice=Choice(message=Message(content="hi")),
)


class _FakeLLM(LLM):
    """Minimal concrete subclass used to exercise `__init_subclass__`."""

    def __init__(self) -> None:
        self._invoke_calls = 0
        self._stream_calls = 0
        self._last_prompt: Any = None

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="test",
            model_name="test-model",
            temperature=0.0,
            max_input_tokens=1000,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        self._invoke_calls += 1
        self._last_prompt = prompt
        return _TEST_MODEL_RESPONSE

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        self._stream_calls += 1
        self._last_prompt = prompt
        for chunk_text in ("hello", " ", "world"):
            yield ModelResponseStream(
                id="stream-id",
                created="2026-04-22T00:00:00Z",
                choice=StreamingChoice(delta=Delta(content=chunk_text)),
            )


class _NoOverrideLLM(_FakeLLM):
    """Subclass that does not override ``invoke`` / ``stream`` — the inherited
    (already-wrapped) methods must not be wrapped a second time."""


def test_init_subclass_auto_wraps_invoke_and_stream() -> None:
    assert getattr(_FakeLLM.invoke, _ALREADY_WRAPPED_ATTR, False) is True
    assert getattr(_FakeLLM.stream, _ALREADY_WRAPPED_ATTR, False) is True


def test_inherited_methods_are_not_rewrapped() -> None:
    # _NoOverrideLLM inherits from _FakeLLM without redefining invoke/stream,
    # so __init_subclass__ should not wrap them again.
    assert _NoOverrideLLM.invoke is _FakeLLM.invoke
    assert _NoOverrideLLM.stream is _FakeLLM.stream


def test_wrap_invoke_is_idempotent() -> None:
    # Calling wrap_invoke on an already-wrapped function returns the same
    # function instance rather than wrapping it again.
    wrapped_once = _FakeLLM.invoke
    wrapped_twice = wrap_invoke(wrapped_once)
    assert wrapped_twice is wrapped_once


def test_wrap_stream_is_idempotent() -> None:
    wrapped_once = _FakeLLM.stream
    wrapped_twice = wrap_stream(wrapped_once)
    assert wrapped_twice is wrapped_once


def test_invoke_returns_inner_response() -> None:
    llm = _FakeLLM()
    prompt = UserMessage(content="hello")
    result = llm.invoke(prompt)
    assert result is _TEST_MODEL_RESPONSE
    assert llm._invoke_calls == 1
    assert llm._last_prompt is prompt


def test_stream_yields_all_chunks() -> None:
    llm = _FakeLLM()
    prompt = UserMessage(content="hello")
    chunks = list(llm.stream(prompt))
    assert len(chunks) == 3
    assert llm._stream_calls == 1
    assert llm._last_prompt is prompt


def test_outer_guard_false_when_no_span_active() -> None:
    assert _outer_generation_span_active() is False


def test_outer_guard_true_inside_generation_span() -> None:
    # An active trace is required for `generation_span` to return a real
    # SpanImpl rather than a NoOpSpan (see provider.py).
    with trace("test_outer_guard_true"):
        with generation_span(model="test", model_config={"model_provider": "test"}):
            assert _outer_generation_span_active() is True
    # Span exited cleanly — contextvar reset, guard flips back to False.
    assert _outer_generation_span_active() is False


def test_outer_guard_false_for_finished_span_leaked_into_contextvar() -> None:
    """Regression guard for the ``GeneratorExit`` corner case.

    ``SpanImpl.__exit__`` intentionally skips ``Scope.reset_current_span``
    when the exit was triggered by ``GeneratorExit`` (abandoned streaming
    generator). That leaves a finished span object in the contextvar.
    The outer-span guard must ignore it so subsequent LLM calls in the same
    asyncio task still receive fallback tracing.
    """
    with trace("test_stale_span_guard"):
        span = generation_span(model="test", model_config={"model_provider": "test"})
        # Simulate the GeneratorExit exit path: start the span so it lives
        # in the contextvar, then call __exit__ with GeneratorExit, which
        # sets ended_at but does NOT reset the contextvar.
        span.start(mark_as_current=True)
        span.__exit__(GeneratorExit, GeneratorExit(), None)
        try:
            assert span.ended_at is not None  # span is finished
            assert _outer_generation_span_active() is False
        finally:
            # Clean up the leaked contextvar so later code in this test
            # isn't polluted.
            span.finish(reset_current=True)


# `functools.wraps` sets __wrapped__ on the auto-wrapped methods so the
# underlying (undecorated) function is reachable for signature introspection.
# mypy doesn't know about this attribute on the Callable type, so we access
# it via getattr below.


def test_extract_prompt_reads_positional_arg() -> None:
    llm = _FakeLLM()
    sig = _validate_prompt_param(getattr(_FakeLLM.invoke, "__wrapped__"))
    assert _extract_prompt(sig, llm, ("hi",), {}) == "hi"


def test_extract_prompt_reads_keyword_arg() -> None:
    llm = _FakeLLM()
    sig = _validate_prompt_param(getattr(_FakeLLM.invoke, "__wrapped__"))
    assert _extract_prompt(sig, llm, (), {"prompt": "hi"}) == "hi"


def test_extract_prompt_returns_none_on_signature_mismatch() -> None:
    """Unknown keyword arguments don't match the signature → bind fails →
    extraction returns None rather than raising."""
    llm = _FakeLLM()
    sig = _validate_prompt_param(getattr(_FakeLLM.invoke, "__wrapped__"))
    assert _extract_prompt(sig, llm, (), {"not_a_real_param": "hi"}) is None


def test_validate_prompt_param_rejects_signature_without_prompt() -> None:
    # Fixed parameter list with no ``prompt``, no ``*args``, no ``**kwargs``
    # — the override cannot receive a prompt at all, so validation fails.
    def bad_override(self: object, foo: str) -> None:  # noqa: ARG001
        return None

    with pytest.raises(TypeError, match="signature cannot accept a 'prompt' argument"):
        _validate_prompt_param(bad_override)


def test_validate_prompt_param_accepts_catch_all_signature() -> None:
    """Test doubles commonly override with ``*args, **kwargs`` catch-all.
    Those signatures can accept a prompt via the variable-keyword parameter,
    so validation must not reject them."""

    def catch_all(self: object, *args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    # Should not raise.
    sig = _validate_prompt_param(catch_all)
    assert sig is not None


def test_wrap_invoke_raises_on_signature_without_prompt() -> None:
    """Wrap-time validation surfaces a clear error at class-creation time so
    subclass signature drift doesn't silently produce blank-input spans."""

    def bad_invoke(self: object, foo: str) -> ModelResponse:  # noqa: ARG001
        raise AssertionError("bad_invoke should never run")

    with pytest.raises(TypeError, match="signature cannot accept a 'prompt' argument"):
        wrap_invoke(cast(Callable[..., ModelResponse], bad_invoke))


def test_invoke_does_not_nest_inside_outer_generation_span() -> None:
    """When an outer caller has already opened a ``generation_span``, the
    fallback wrap must skip creating a new span (so cost is not
    double-counted). We can't observe span creation directly here, but we can
    verify the guard sees the outer span and that the inner call still
    executes and returns the response."""
    llm = _FakeLLM()
    prompt = UserMessage(content="hello")
    with trace("test_no_nesting"):
        with generation_span(model="test", model_config={"model_provider": "test"}):
            assert _outer_generation_span_active() is True
            result = llm.invoke(prompt)
    assert result is _TEST_MODEL_RESPONSE
    assert llm._invoke_calls == 1


@pytest.mark.parametrize("prompt_kind", ["positional", "keyword"])
def test_invoke_records_prompt_via_both_call_styles(prompt_kind: str) -> None:
    llm = _FakeLLM()
    prompt = UserMessage(content=f"p-{prompt_kind}")
    if prompt_kind == "positional":
        llm.invoke(prompt)
    else:
        llm.invoke(prompt=prompt)
    assert llm._last_prompt is prompt


class _ExplodingLLM(LLM):
    """Test double whose `invoke` / `stream` always raise."""

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="test",
            model_name="test-model",
            temperature=0.0,
            max_input_tokens=1000,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        raise RuntimeError("invoke-boom")

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        raise RuntimeError("stream-boom")
        yield  # pragma: no cover — unreachable, keeps this a generator


def test_invoke_propagates_exception_from_inner_call() -> None:
    llm = _ExplodingLLM()
    with pytest.raises(RuntimeError, match="invoke-boom"):
        llm.invoke(UserMessage(content="hi"))


def test_stream_propagates_exception_from_inner_call() -> None:
    llm = _ExplodingLLM()
    with pytest.raises(RuntimeError, match="stream-boom"):
        list(llm.stream(UserMessage(content="hi")))


def test_outer_guard_false_for_noop_span_in_contextvar() -> None:
    """A ``NoOpSpan`` (returned when no trace is active) always has
    ``started_at = None`` and ``ended_at = None``. Without the ``started_at``
    guard, a stale ``NoOpSpan`` left in the contextvar (e.g. after an
    abandoned generator) would cause ``_outer_generation_span_active`` to
    return ``True`` and silently suppress fallback tracing. Verify the guard
    filters it out."""
    # Generating a span outside any `trace()` context returns a NoOpSpan.
    noop_span = generation_span(model="test", model_config={"model_provider": "test"})
    noop_span.start(mark_as_current=True)
    try:
        assert noop_span.started_at is None
        assert _outer_generation_span_active() is False
    finally:
        noop_span.finish(reset_current=True)


# ---------------------------------------------------------------------------
# Tool-call delta reassembly
# ---------------------------------------------------------------------------


def _delta(
    index: int,
    *,
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> ChatCompletionDeltaToolCall:
    fn = (
        DeltaFunctionCall(name=name, arguments=arguments)
        if (name is not None or arguments is not None)
        else None
    )
    return ChatCompletionDeltaToolCall(id=id, index=index, type="function", function=fn)


def test_merge_tool_call_delta_single_call_across_chunks() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    # Chunk 1: id + name + arg fragment 1
    _merge_tool_call_delta(
        buf, _delta(0, id="call_1", name="search", arguments='{"q":"')
    )
    # Chunk 2: arg fragment 2
    _merge_tool_call_delta(buf, _delta(0, arguments="hello"))
    # Chunk 3: arg fragment 3
    _merge_tool_call_delta(buf, _delta(0, arguments='"}'))

    finalized = _finalize_tool_calls(buf)
    assert finalized is not None
    assert len(finalized) == 1
    tc = finalized[0]
    assert tc.id == "call_1"
    assert tc.function.name == "search"
    assert tc.function.arguments == '{"q":"hello"}'


def test_merge_tool_call_delta_multiple_calls_by_index() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    # Interleaved deltas across two tool calls (indices 0 and 1)
    _merge_tool_call_delta(buf, _delta(0, id="call_a", name="fn_a", arguments='{"x":'))
    _merge_tool_call_delta(buf, _delta(1, id="call_b", name="fn_b", arguments='{"y":'))
    _merge_tool_call_delta(buf, _delta(0, arguments="1}"))
    _merge_tool_call_delta(buf, _delta(1, arguments="2}"))

    finalized = _finalize_tool_calls(buf)
    assert finalized is not None
    assert len(finalized) == 2
    # Sorted by index
    assert finalized[0].id == "call_a"
    assert finalized[0].function.name == "fn_a"
    assert finalized[0].function.arguments == '{"x":1}'
    assert finalized[1].id == "call_b"
    assert finalized[1].function.name == "fn_b"
    assert finalized[1].function.arguments == '{"y":2}'


def test_merge_tool_call_delta_does_not_overwrite_first_id_or_name() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    _merge_tool_call_delta(
        buf, _delta(0, id="call_real", name="real_fn", arguments="{}")
    )
    # A later delta that (incorrectly) supplies a different id/name must not
    # clobber the first-seen values.
    _merge_tool_call_delta(
        buf, _delta(0, id="call_ignored", name="ignored_fn", arguments="")
    )
    finalized = _finalize_tool_calls(buf)
    assert finalized is not None
    assert finalized[0].id == "call_real"
    assert finalized[0].function.name == "real_fn"


def test_finalize_tool_calls_skips_entries_missing_required_fields() -> None:
    buf: dict[int, ChatCompletionDeltaToolCall] = {}
    # Complete entry
    _merge_tool_call_delta(buf, _delta(0, id="call_ok", name="fn_ok", arguments="{}"))
    # Incomplete entry — never got an id or name
    _merge_tool_call_delta(buf, _delta(1, arguments='{"partial":true}'))
    finalized = _finalize_tool_calls(buf)
    assert finalized is not None
    assert len(finalized) == 1
    assert finalized[0].id == "call_ok"


def test_finalize_tool_calls_returns_none_for_empty_buffer() -> None:
    assert _finalize_tool_calls({}) is None


class _ToolStreamLLM(LLM):
    """Test double that streams one tool call split across three chunks."""

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="test",
            model_name="test-model",
            temperature=0.0,
            max_input_tokens=1000,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        return _TEST_MODEL_RESPONSE

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        frames = [
            _delta(0, id="call_1", name="search", arguments='{"q":"'),
            _delta(0, arguments="hi"),
            _delta(0, arguments='"}'),
        ]
        for delta_tc in frames:
            yield ModelResponseStream(
                id="stream-id",
                created="2026-04-22T00:00:00Z",
                choice=StreamingChoice(delta=Delta(tool_calls=[delta_tc])),
            )


def test_stream_forwards_every_chunk_unchanged_when_tool_calls_present() -> None:
    """Regression guard: the wrap must not alter the yielded chunks even
    while it accumulates tool-call deltas internally."""
    llm = _ToolStreamLLM()
    chunks = list(llm.stream(UserMessage(content="hi")))
    assert len(chunks) == 3
    # The deltas yielded downstream still look like partial fragments.
    assert chunks[0].choice.delta.tool_calls[0].id == "call_1"
    assert chunks[1].choice.delta.tool_calls[0].id is None  # fragment
    assert chunks[2].choice.delta.tool_calls[0].id is None  # fragment


# ---------------------------------------------------------------------------
# Usage recording on non-clean stream exits
# ---------------------------------------------------------------------------


_TEST_USAGE = Usage(
    completion_tokens=10,
    prompt_tokens=200,
    total_tokens=210,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=0,
)


class _UsageStreamLLM(LLM):
    """Test double that yields a usage chunk first, then content chunks.

    Mirrors the real LiteLLM streaming order where the first chunk often
    carries cumulative ``usage`` even before all content has been emitted.
    """

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="test",
            model_name="test-model",
            temperature=0.0,
            max_input_tokens=1000,
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        return _TEST_MODEL_RESPONSE

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        yield ModelResponseStream(
            id="stream-id",
            created="2026-04-22T00:00:00Z",
            choice=StreamingChoice(delta=Delta(content="hello")),
            usage=_TEST_USAGE,
        )
        yield ModelResponseStream(
            id="stream-id",
            created="2026-04-22T00:00:00Z",
            choice=StreamingChoice(delta=Delta(content=" world")),
        )


class _UsageThenExplodeLLM(_UsageStreamLLM):
    """Yields one usage-bearing chunk, then raises mid-stream."""

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        yield ModelResponseStream(
            id="stream-id",
            created="2026-04-22T00:00:00Z",
            choice=StreamingChoice(delta=Delta(content="hello")),
            usage=_TEST_USAGE,
        )
        raise RuntimeError("stream-mid-boom")


def test_stream_records_usage_when_consumer_abandons_generator() -> None:
    """Consumer reads the first chunk (which carries usage) then closes the
    generator without exhausting it. The wrap must still record the usage
    seen so far so cost attribution doesn't silently zero out — the upstream
    provider already billed for those tokens."""
    llm = _UsageStreamLLM()
    with patch("onyx.tracing.llm_utils.record_llm_span_output") as recorder:
        gen = cast(
            Generator[ModelResponseStream, None, None],
            llm.stream(UserMessage(content="hi")),
        )
        first_chunk = next(gen)
        assert first_chunk.choice.delta.content == "hello"
        gen.close()  # triggers GeneratorExit inside the wrap
    recorder.assert_called_once()
    kwargs = recorder.call_args.kwargs
    assert kwargs["usage"] == _TEST_USAGE
    assert kwargs["output"] == "hello"


def test_stream_records_usage_when_inner_stream_raises_mid_flight() -> None:
    """Provider streams a usage-bearing chunk, then raises. Wrap must
    record the usage seen before the failure so cost is attributed
    correctly even though the consumer never saw a clean completion."""
    llm = _UsageThenExplodeLLM()
    with patch("onyx.tracing.llm_utils.record_llm_span_output") as recorder:
        with pytest.raises(RuntimeError, match="stream-mid-boom"):
            list(llm.stream(UserMessage(content="hi")))
    recorder.assert_called_once()
    kwargs = recorder.call_args.kwargs
    assert kwargs["usage"] == _TEST_USAGE
    assert kwargs["output"] == "hello"
