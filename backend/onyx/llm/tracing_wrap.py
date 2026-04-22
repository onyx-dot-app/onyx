"""Auto-tracing wrapper applied to every concrete `LLM` subclass.

Every concrete subclass of `onyx.llm.interfaces.LLM` has its `invoke` and
`stream` methods auto-wrapped via `LLM.__init_subclass__` so that every LLM
call lands in Braintrust without per-callsite instrumentation. The wrap is a
no-op when an outer `generation_span` is already active — callers that
explicitly wrap their calls (via `llm_generation_span`) continue to work and
are not double-counted.

Imports from `onyx.tracing.*` are performed lazily inside the wrappers to
avoid an import cycle between `onyx.llm.interfaces` and
`onyx.tracing.llm_utils` (which itself imports `LLM`).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLM
    from onyx.llm.model_response import ModelResponse
    from onyx.llm.model_response import ModelResponseStream


_ALREADY_WRAPPED_ATTR = "_onyx_tracing_wrapped"


def _outer_generation_span_active() -> bool:
    """Return True when an outer caller has already opened a generation_span.

    The fallback wrap becomes a no-op in that case so we don't double-count
    cost or produce nested duplicate spans in Braintrust.
    """
    from onyx.tracing.framework.create import get_current_span
    from onyx.tracing.framework.span_data import GenerationSpanData

    current = get_current_span()
    return current is not None and isinstance(current.span_data, GenerationSpanData)


def wrap_invoke(
    invoke_fn: Callable[..., "ModelResponse"],
) -> Callable[..., "ModelResponse"]:
    """Wrap a concrete ``LLM.invoke`` implementation with a fallback generation_span."""
    if getattr(invoke_fn, _ALREADY_WRAPPED_ATTR, False):
        return invoke_fn

    @functools.wraps(invoke_fn)
    def wrapper(self: "LLM", *args: Any, **kwargs: Any) -> "ModelResponse":
        if _outer_generation_span_active():
            return invoke_fn(self, *args, **kwargs)

        from onyx.tracing.llm_utils import llm_generation_span
        from onyx.tracing.llm_utils import record_llm_response

        with llm_generation_span(self, flow="llm_invoke_fallback") as span:
            response = invoke_fn(self, *args, **kwargs)
            if span is not None and response is not None:
                record_llm_response(span, response)
            return response

    setattr(wrapper, _ALREADY_WRAPPED_ATTR, True)
    return wrapper


def wrap_stream(
    stream_fn: Callable[..., Iterator["ModelResponseStream"]],
) -> Callable[..., Iterator["ModelResponseStream"]]:
    """Wrap a concrete ``LLM.stream`` implementation with a fallback generation_span.

    Accumulates content + final usage across yielded chunks and records them on
    the span when the stream is fully consumed. Tool-call deltas are
    intentionally NOT accumulated — streaming deltas are partial fragments
    keyed on ``index`` that need ``litellm.stream_chunk_builder``-style
    reassembly before being safe to log.
    """
    if getattr(stream_fn, _ALREADY_WRAPPED_ATTR, False):
        return stream_fn

    @functools.wraps(stream_fn)
    def wrapper(
        self: "LLM", *args: Any, **kwargs: Any
    ) -> Iterator["ModelResponseStream"]:
        if _outer_generation_span_active():
            yield from stream_fn(self, *args, **kwargs)
            return

        from onyx.llm.model_response import Usage
        from onyx.tracing.llm_utils import llm_generation_span
        from onyx.tracing.llm_utils import record_llm_span_output

        with llm_generation_span(self, flow="llm_stream_fallback") as span:
            accumulated_content: list[str] = []
            final_usage: Usage | None = None

            for chunk in stream_fn(self, *args, **kwargs):
                if chunk.usage:
                    final_usage = chunk.usage
                if span is not None and chunk.choice.delta.content:
                    accumulated_content.append(chunk.choice.delta.content)
                yield chunk

            # Only reached on clean stream completion. If the consumer abandons
            # the generator or an exception propagates, the context manager
            # exits via __exit__ without output set.
            if span is not None:
                record_llm_span_output(
                    span,
                    output="".join(accumulated_content) or None,
                    usage=final_usage,
                    tool_calls=None,
                )

    setattr(wrapper, _ALREADY_WRAPPED_ATTR, True)
    return wrapper
