"""Shared SSE-over-thread streaming primitives for the LLM gateway.

Moved verbatim out of ``onyx.server.gateway.api`` so both the translation
path (api.py) and the Anthropic native passthrough path
(anthropic_passthrough.py) can share them without a circular import.
"""

import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol, runtime_checkable

from fastapi.responses import StreamingResponse

from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    ModelResponseStream,
    Usage,
)
from onyx.llm.multi_llm import LLMRateLimitError, LLMTimeoutError
from onyx.llm.tracing_wrap import _finalize_tool_calls, _merge_tool_call_delta
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.llm_utils import record_llm_span_output
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

logger = setup_logger()

_STREAM_END = object()


@runtime_checkable
class _ClosableStream(Protocol):
    """LLM.stream is declared Iterator, which carries no close(); every real
    implementation is a generator, and an abandoned one must be closed so the
    provider connection is released."""

    def close(self) -> None: ...


def _put_stream_item(
    out: "queue.Queue[Any]", item: Any, cancelled: threading.Event
) -> bool:
    while not cancelled.is_set():
        try:
            out.put(item, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


class _StreamAccumulator:
    def __init__(self) -> None:
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.usage: Usage | None = None
        self.tool_call_buffer: dict[int, ChatCompletionDeltaToolCall] = {}
        # Iterator[ModelResponseStream] for LLM.stream(); an ExitStack for the
        # Anthropic passthrough, which must close both the httpx response and
        # client. Only the presence of .close() (_ClosableStream) is relied on.
        self.upstream: Iterator[ModelResponseStream] | _ClosableStream | None = None

    def observe(self, chunk: ModelResponseStream) -> None:
        if chunk.usage:
            self.usage = chunk.usage
        if chunk.choice.delta.content:
            self.content.append(chunk.choice.delta.content)
        if chunk.choice.delta.reasoning_content:
            self.reasoning.append(chunk.choice.delta.reasoning_content)
        for delta_tc in chunk.choice.delta.tool_calls:
            _merge_tool_call_delta(self.tool_call_buffer, delta_tc)

    @property
    def text(self) -> str:
        return "".join(self.content)


_RATE_LIMIT_ERROR = (
    "The selected model is temporarily rate limited.",
    "rate_limit_error",
)
_TIMEOUT_ERROR = ("The selected model did not respond in time.", "timeout_error")
_UPSTREAM_ERROR = ("The upstream LLM request failed.", "upstream_error")


@contextmanager
def _stream_worker_guard(
    span: Span[GenerationSpanData] | None,
    model: str,
    state: _StreamAccumulator,
    *,
    label: str,
    emit_error: Callable[..., None],
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> Iterator[None]:
    """The HTTP status is already sent by the time a worker runs, so upstream
    failures surface in-band as a protocol error frame rather than raising."""
    try:
        yield
    except Exception as exc:
        if isinstance(exc, LLMRateLimitError):
            message, error_type = _RATE_LIMIT_ERROR
        elif isinstance(exc, LLMTimeoutError):
            message, error_type = _TIMEOUT_ERROR
        else:
            message, error_type = _UPSTREAM_ERROR
        if span is not None:
            span.set_error({"message": f"{type(exc).__name__}: {exc}", "data": None})
        logger.exception(
            "LLM gateway %s failed (%s) for model %s", label, error_type, model
        )
        emit_error(message=message, error_type=error_type)
    finally:
        try:
            if isinstance(state.upstream, _ClosableStream):
                state.upstream.close()
        except Exception:
            logger.exception("LLM gateway %s cleanup failed for model %s", label, model)
        try:
            if span is not None:
                record_llm_span_output(
                    span,
                    output=state.text or None,
                    usage=state.usage,
                    reasoning="".join(state.reasoning) or None,
                    tool_calls=_finalize_tool_calls(state.tool_call_buffer),
                )
        except Exception:
            logger.exception(
                "LLM gateway %s span cleanup failed for model %s", label, model
            )
        finally:
            _put_stream_item(out, _STREAM_END, cancelled)


def _run_bridged_stream(
    worker: Callable[..., None], worker_kwargs: dict[str, Any]
) -> Iterator[str]:
    """Bridge a stream worker through a queue so the whole consumption —
    including the generation span's ContextVar enter/exit — happens on ONE
    thread. Yielding directly from a sync generator breaks under Starlette,
    which resumes the generator on varying threadpool threads (ContextVar
    tokens can't be reset across contexts)."""
    out: "queue.Queue[Any]" = queue.Queue(maxsize=256)
    cancelled = threading.Event()
    worker_thread = start_thread_with_context(
        worker,
        name="llm-gateway-stream",
        daemon=True,
        kwargs={**worker_kwargs, "out": out, "cancelled": cancelled},
    )
    try:
        while True:
            if worker_thread.is_alive():
                try:
                    item = out.get(timeout=0.5)
                except queue.Empty:
                    continue
            else:
                # Worker died before signalling: drain, or the stream truncates.
                try:
                    item = out.get_nowait()
                except queue.Empty:
                    return
            if item is _STREAM_END:
                return
            yield item
    finally:
        cancelled.set()


def _sse_response(
    worker: Callable[..., None], worker_kwargs: dict[str, Any]
) -> StreamingResponse:
    return StreamingResponse(
        _run_bridged_stream(worker, worker_kwargs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
