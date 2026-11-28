"""Writes one ``gateway.llm_request`` audit event per LLM gateway call made
by an external client (the ``llm_gateway`` flow).

A tracing processor sees the generation span of every gateway path (chat
completions, responses, messages, provider passthroughs, streaming or not),
so the event needs no per-route code. Token counts come from the span; prompt
and completion text never reach the event. Craft sandbox calls use the same
routes under the ``craft_llm_generation`` flow and are left out on purpose:
they are the Craft agent's own steps, not a user's request.
"""

from typing import Any

from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_request_context,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _token_count(usage: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = usage.get(name)
        if value is not None:
            return int(value)
    return None


class GatewayAuditTracingProcessor(TracingProcessor):
    def on_trace_start(self, trace: Trace) -> None:
        pass

    def on_trace_end(self, trace: Trace) -> None:
        pass

    def on_span_start(self, span: Span[Any]) -> None:
        pass

    def on_span_end(self, span: Span[Any]) -> None:
        # Never raise into the LLM path.
        try:
            data = span.span_data
            if not isinstance(data, GenerationSpanData):
                return
            model_config = data.model_config or {}
            if model_config.get("flow") != LLMFlow.LLM_GATEWAY.value:
                return
            usage = data.usage or {}
            emit_audit_event(
                AuditAction.GATEWAY_LLM_REQUEST,
                (
                    AuditOutcome.FAILURE
                    if span.error is not None
                    else AuditOutcome.SUCCESS
                ),
                actor=actor_from_request_context(),
                extra={
                    "model_provider": model_config.get("model_provider"),
                    "model": data.model,
                    "routed_model": data.routed_model,
                    "input_tokens": _token_count(
                        usage, "input_tokens", "prompt_tokens"
                    ),
                    "output_tokens": _token_count(
                        usage, "output_tokens", "completion_tokens"
                    ),
                },
            )
        except Exception:
            logger.exception("Gateway audit processor failed")

    def shutdown(self) -> None:
        pass

    def force_flush(self) -> None:
        pass


def build_audit_tracing_processor() -> TracingProcessor:
    return GatewayAuditTracingProcessor()
