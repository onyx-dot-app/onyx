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
import inspect
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLM
    from onyx.llm.model_response import ModelResponse
    from onyx.llm.model_response import ModelResponseStream


_ALREADY_WRAPPED_ATTR = "_onyx_tracing_wrapped"
_PROMPT_PARAM_NAME = "prompt"


def _outer_generation_span_active() -> bool:
    """Return True when an outer caller has already opened a generation_span.

    The fallback wrap becomes a no-op in that case so we don't double-count
    cost or produce nested duplicate spans in Braintrust.

    Uses both ``started_at is not None`` and ``ended_at is None`` to reject
    two edge cases:

    - ``SpanImpl.__exit__`` intentionally skips ``Scope.reset_current_span``
      when the exit was triggered by ``GeneratorExit`` (streaming consumer
      abandoned the generator early). That leaves a finished span in the
      contextvar; the ``ended_at`` check filters it out.
    - ``NoOpSpan`` (returned when tracing is disabled or no trace is active)
      always has ``started_at = None``. The ``started_at`` check prevents a
      stale ``NoOpSpan`` from suppressing fallback tracing.
    """
    from onyx.tracing.framework.create import get_current_span
    from onyx.tracing.framework.span_data import GenerationSpanData

    current = get_current_span()
    return (
        current is not None
        and isinstance(current.span_data, GenerationSpanData)
        and current.started_at is not None
        and current.ended_at is None
    )


def _validate_prompt_param(fn: Callable[..., Any]) -> inspect.Signature:
    """Return the signature of ``fn``, asserting it can accept a ``prompt``.

    Runs once at wrap time so a subclass whose ``invoke`` / ``stream``
    signature can't possibly carry a ``prompt`` surfaces a clear error at
    class creation rather than silently producing blank-input spans at
    runtime.

    An override is considered valid if it has any of:
    - a named ``prompt`` parameter (the expected shape), or
    - a ``**kwargs`` (VAR_KEYWORD) parameter that could carry it, or
    - an ``*args`` (VAR_POSITIONAL) parameter that could carry it.

    Test doubles commonly use ``*args, **kwargs`` catch-alls to ignore the
    full signature — those are accepted here. Only overrides that *can't*
    receive a prompt at all (e.g. a fixed unrelated parameter list) are
    rejected.
    """
    sig = inspect.signature(fn)
    params = sig.parameters.values()
    has_prompt = _PROMPT_PARAM_NAME in sig.parameters
    accepts_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    accepts_var_positional = any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params
    )
    if not (has_prompt or accepts_var_keyword or accepts_var_positional):
        name = getattr(fn, "__qualname__", repr(fn))
        raise TypeError(
            f"Cannot auto-trace {name}: signature cannot accept a "
            f"'{_PROMPT_PARAM_NAME}' argument. LLM.invoke / LLM.stream "
            f"subclass overrides must either keep the 'prompt' parameter "
            f"name or accept *args / **kwargs."
        )
    return sig


def _extract_prompt(
    sig: inspect.Signature,
    self_: "LLM",
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any | None:
    """Bind ``args`` / ``kwargs`` against ``sig`` and return the ``prompt`` value.

    Uses ``Signature.bind`` so extraction is robust to any mix of positional
    / keyword argument passing and immune to future parameter reordering.
    Returns ``None`` if the arguments don't match the signature — the
    fallback span will simply omit input messages rather than fail the
    request.
    """
    try:
        bound = sig.bind(self_, *args, **kwargs)
    except TypeError:
        return None
    return bound.arguments.get(_PROMPT_PARAM_NAME)


def wrap_invoke(
    invoke_fn: Callable[..., "ModelResponse"],
) -> Callable[..., "ModelResponse"]:
    """Wrap a concrete ``LLM.invoke`` implementation with a fallback generation_span."""
    if getattr(invoke_fn, _ALREADY_WRAPPED_ATTR, False):
        return invoke_fn

    sig = _validate_prompt_param(invoke_fn)

    @functools.wraps(invoke_fn)
    def wrapper(self: "LLM", *args: Any, **kwargs: Any) -> "ModelResponse":
        if _outer_generation_span_active():
            return invoke_fn(self, *args, **kwargs)

        from onyx.tracing.llm_utils import llm_generation_span
        from onyx.tracing.llm_utils import record_llm_response

        prompt = _extract_prompt(sig, self, args, kwargs)
        with llm_generation_span(
            self, flow="llm_invoke_fallback", input_messages=prompt
        ) as span:
            try:
                response = invoke_fn(self, *args, **kwargs)
            except Exception as exc:
                if span is not None:
                    span.set_error(
                        {
                            "message": f"{type(exc).__name__}: {exc}",
                            "data": None,
                        }
                    )
                raise
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

    sig = _validate_prompt_param(stream_fn)

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

        prompt = _extract_prompt(sig, self, args, kwargs)
        with llm_generation_span(
            self, flow="llm_stream_fallback", input_messages=prompt
        ) as span:
            accumulated_content: list[str] = []
            final_usage: Usage | None = None

            try:
                for chunk in stream_fn(self, *args, **kwargs):
                    if chunk.usage:
                        final_usage = chunk.usage
                    if span is not None and chunk.choice.delta.content:
                        accumulated_content.append(chunk.choice.delta.content)
                    yield chunk
            except Exception as exc:
                if span is not None:
                    span.set_error(
                        {
                            "message": f"{type(exc).__name__}: {exc}",
                            "data": None,
                        }
                    )
                raise

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
