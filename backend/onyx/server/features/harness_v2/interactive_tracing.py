"""Trace each interactive harness without replacing Onyx's tracing delegates."""

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

_lock = threading.Lock()

if TYPE_CHECKING:
    import braintrust

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor

_logger: "braintrust.Logger | None" = None
_processor: "BraintrustTracingProcessor | None" = None


@contextmanager
def trace_run(request: Any, user_id: str) -> Iterator[Any]:
    global _logger, _processor
    project = os.environ.get("HARNESS_BRAINTRUST_PROJECT_ID")
    if not project:
        yield None
        return
    import braintrust

    with _lock:
        if _logger is None:
            from onyx.tracing.braintrust_tracing_processor import (
                BraintrustTracingProcessor,
            )
            from onyx.tracing.framework import add_trace_processor

            class InteractiveProcessor(BraintrustTracingProcessor):
                # Only own explicitly marked harness traces. Existing or
                # in-flight normal chat traces keep their original delegates.
                def on_trace_start(self, trace):
                    if ((trace.export() or {}).get("metadata") or {}).get(
                        "harness_chat_v2"
                    ):
                        super().on_trace_start(trace)

                def on_trace_end(self, trace):
                    if (
                        trace.trace_id in self._spans
                        or trace.trace_id in self._suppressed_traces
                    ):
                        super().on_trace_end(trace)

                def on_span_start(self, span):
                    if span.trace_id in self._spans:
                        super().on_span_start(span)

                def on_span_end(self, span):
                    if span.span_id in self._spans:
                        super().on_span_end(span)

            _logger = braintrust.init_logger(
                project_id=project,
                api_key=os.environ["BRAINTRUST_API_KEY"],
                async_flush=False,
                set_current=False,
            )
            _processor = InteractiveProcessor(_logger)
            add_trace_processor(_processor)
        logger = _logger
        processor = _processor
    if logger is None or processor is None:
        raise RuntimeError("Harness interactive tracing did not initialize")
    from onyx.tracing.framework.create import trace
    from onyx.tracing.framework.scope import Scope

    # SDK link() consults a ContextVar even for an explicit logger.
    logger_token = cast(Any, logger.state)._cv_logger.set(logger)
    span_token = Scope.set_current_span(None)
    trace_token = Scope.set_current_trace(None)
    try:
        metadata = {
            "experiment": "interactive-repairs-20260914",
            "harness": "v2",
            "harness_chat_v2": True,
            "user_id": user_id,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort.value,
            "policy": request.policy.model_dump(),
        }
        with logger.start_span(
            name="harness-v2/interactive",
            type=braintrust.SpanTypeAttribute.TASK,
            input=request.question,
            metadata=metadata,
        ) as span:
            with trace("harness-v2/chat-loop", metadata=metadata):
                yield span
        processor.force_flush()
    finally:
        Scope.reset_current_trace(trace_token)
        Scope.reset_current_span(span_token)
        cast(Any, logger.state)._cv_logger.reset(logger_token)
