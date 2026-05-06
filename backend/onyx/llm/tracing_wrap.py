"""Auto-tracing wrapper applied to every concrete `LLM` subclass.

Every concrete subclass of `onyx.llm.interfaces.LLM` has its `invoke` and
`stream` methods auto-wrapped via `LLM.__init_subclass__` so that every LLM
call lands in Braintrust without per-callsite instrumentation. The wrap is a
no-op when an outer `generation_span` is already active — callers that
explicitly wrap their calls (via `llm_generation_span`) continue to work and
are not double-counted.

Imports from `onyx.tracing.llm_utils` stay lazy (inside the wrappers) because
it imports `onyx.llm.interfaces`, which imports this module — loading it at
module level would deadlock the import graph. Everything else is imported
at the top of the file.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import TYPE_CHECKING

from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import FunctionCall as DeltaFunctionCall
from onyx.llm.model_response import Usage
from onyx.tracing.framework.create import get_current_span
from onyx.tracing.framework.span_data import GenerationSpanData

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLM
    from onyx.llm.model_response import ModelResponse
    from onyx.llm.model_response import ModelResponseStream
    from onyx.llm.models import ToolCall


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

        from onyx.tracing.flows import LLMFlow
        from onyx.tracing.llm_utils import llm_generation_span
        from onyx.tracing.llm_utils import record_llm_response

        prompt = _extract_prompt(sig, self, args, kwargs)
        with llm_generation_span(
            self, flow=LLMFlow.UNTAGGED_INVOKE, input_messages=prompt
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

    Accumulates content, final usage, and tool-call deltas across yielded
    chunks and records them on the span on every exit path — clean
    completion, ``Exception`` propagation, or ``GeneratorExit`` from an
    abandoned consumer. Recording in ``finally`` is required because
    Anthropic / OpenAI bill for every token streamed up to the point of
    abandonment, so cost attribution would silently zero out without it.

    Tool-call deltas arrive as partial fragments keyed on ``index`` — this
    wrap reassembles them via ``_merge_tool_call_delta`` before logging so
    Braintrust shows one complete tool-call entry per invocation rather than
    fragmented duplicates.
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

        from onyx.tracing.flows import LLMFlow
        from onyx.tracing.llm_utils import llm_generation_span
        from onyx.tracing.llm_utils import record_llm_span_output

        prompt = _extract_prompt(sig, self, args, kwargs)
        with llm_generation_span(
            self, flow=LLMFlow.UNTAGGED_STREAM, input_messages=prompt
        ) as span:
            accumulated_content: list[str] = []
            final_usage: Usage | None = None
            tool_call_buffer: dict[int, ChatCompletionDeltaToolCall] = {}

            try:
                for chunk in stream_fn(self, *args, **kwargs):
                    if chunk.usage:
                        final_usage = chunk.usage
                    if span is not None and chunk.choice.delta.content:
                        accumulated_content.append(chunk.choice.delta.content)
                    if span is not None and chunk.choice.delta.tool_calls:
                        for delta_tc in chunk.choice.delta.tool_calls:
                            _merge_tool_call_delta(tool_call_buffer, delta_tc)
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
            finally:
                # Anthropic / OpenAI bill for every token streamed up to the
                # point of consumer abandonment, so the span must capture
                # whatever usage and content was seen — not only on clean
                # completion. Recording in ``finally`` covers three exit
                # paths: normal end, ``Exception`` re-raised above, and
                # ``GeneratorExit`` from an abandoned consumer (which does
                # not go through the ``except Exception`` branch since it
                # subclasses ``BaseException`` rather than ``Exception``).
                if span is not None:
                    record_llm_span_output(
                        span,
                        output="".join(accumulated_content) or None,
                        usage=final_usage,
                        tool_calls=_finalize_tool_calls(tool_call_buffer),
                    )

    setattr(wrapper, _ALREADY_WRAPPED_ATTR, True)
    return wrapper


def _merge_tool_call_delta(
    buffer: dict[int, "ChatCompletionDeltaToolCall"],
    delta: "ChatCompletionDeltaToolCall",
) -> None:
    """Merge a single streaming tool-call delta into the per-``index`` buffer.

    Streaming tool calls from LiteLLM arrive as partial fragments:
    - Early chunks for a given ``index`` usually carry ``id`` and
      ``function.name`` (and possibly the first slice of ``function.arguments``).
    - Subsequent chunks for the same ``index`` carry additional
      ``function.arguments`` fragments with ``id`` / ``name`` set to ``None``.

    This helper merges them in place: it preserves the first seen ``id`` and
    ``function.name`` and concatenates ``function.arguments`` fragments. The
    result is a dict of complete ``ChatCompletionDeltaToolCall`` objects
    keyed by ``index`` that can be converted to fully-formed ``ToolCall``
    objects via :func:`_finalize_tool_calls`.
    """
    existing = buffer.get(delta.index)
    if existing is None:
        # Copy into a fresh pydantic model so later mutations don't leak back
        # into the caller's chunk object.
        delta_fn = delta.function
        buffer[delta.index] = ChatCompletionDeltaToolCall(
            id=delta.id,
            index=delta.index,
            type=delta.type,
            function=(
                DeltaFunctionCall(
                    name=delta_fn.name if delta_fn else None,
                    arguments=delta_fn.arguments if delta_fn else None,
                )
                if delta_fn is not None
                else None
            ),
        )
        return

    if delta.id and not existing.id:
        existing.id = delta.id
    if delta.function is not None:
        if existing.function is None:
            existing.function = DeltaFunctionCall(
                name=delta.function.name,
                arguments=delta.function.arguments,
            )
        else:
            if delta.function.name and not existing.function.name:
                existing.function.name = delta.function.name
            if delta.function.arguments:
                existing.function.arguments = (
                    existing.function.arguments or ""
                ) + delta.function.arguments


def _finalize_tool_calls(
    buffer: dict[int, "ChatCompletionDeltaToolCall"],
) -> list["ToolCall"] | None:
    """Convert a reassembled delta buffer into a list of complete ``ToolCall``.

    Entries missing a required field (``id`` or ``function.name``) are skipped
    — these would indicate a truncated / malformed stream, and it's safer to
    log nothing for that index than to fabricate a partial record.
    """
    if not buffer:
        return None

    from onyx.llm.models import FunctionCall as ModelFunctionCall
    from onyx.llm.models import ToolCall

    finalized: list[ToolCall] = []
    for idx in sorted(buffer.keys()):
        delta = buffer[idx]
        if delta.id is None or delta.function is None or delta.function.name is None:
            continue
        finalized.append(
            ToolCall(
                id=delta.id,
                type="function",
                function=ModelFunctionCall(
                    name=delta.function.name,
                    arguments=delta.function.arguments or "",
                ),
            )
        )
    return finalized or None
