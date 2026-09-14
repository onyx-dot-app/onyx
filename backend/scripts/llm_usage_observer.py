"""Process-local, opt-in telemetry for headless LLM calls; no prompt text is saved."""

from __future__ import annotations

import contextvars
import functools
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


def operation_name() -> str:
    """Identify known call sites even when external tracing is disabled."""
    frame = sys._getframe(1)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        name = frame.f_code.co_name
        if module.startswith("onyx.secondary_llm_flows.") and name in {
            "semantic_query_rephrase",
            "keyword_query_expansion",
            "select_sections_for_expansion",
            "classify_section_relevance",
            "select_chunks_for_relevance",
        }:
            return name
        if module == "onyx.agents.v2.llm" and name == "decide":
            return "outer_decision"
        frame = frame.f_back
    return "unknown"


def install_usage_observer(
    ledger_type: Any,
    llm_type: Any,
    output: Path,
    write_json: Callable[[Path, object], None],
    operation: Callable[[], str] = operation_name,
) -> Callable[[], None]:
    """Observe original methods unchanged; caller may restore after all calls finish."""
    active: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
        "headless_llm_usage", default=None
    )
    sequence = 0
    lock = threading.Lock()
    origin = time.monotonic()
    original_invoke = llm_type.invoke
    original_estimate = ledger_type.estimate_tokens
    original_reserve = ledger_type.reserve_llm_call
    original_success = ledger_type.record_success
    original_failure = ledger_type.record_failure

    def elapsed_ms() -> float:
        return (time.monotonic() - origin) * 1000

    @functools.wraps(original_invoke)
    def invoke(self, *args, **kwargs):
        nonlocal sequence
        with lock:
            sequence += 1
            index = sequence
        record: dict[str, Any] = {
            "call_id": index,
            "operation": operation(),
            "started_at_ms": elapsed_ms(),
            "usage": None,
            "status": "started",
        }
        token = active.set(record)
        try:
            result = original_invoke(self, *args, **kwargs)
            record["finish_reason"] = result.choice.finish_reason
            record["status"] = "success"
            return result
        except Exception as exc:
            record.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            record["finished_at_ms"] = elapsed_ms()
            record["total_ms"] = record["finished_at_ms"] - record["started_at_ms"]
            active.reset(token)
            write_json(output / f"llm-call-{index:04d}.json", record)

    @functools.wraps(original_estimate)
    def estimate(self, *args, **kwargs):
        started = elapsed_ms()
        result = original_estimate(self, *args, **kwargs)
        record = active.get()
        if record is not None:
            record.update(
                estimated_prompt_tokens=result,
                token_estimation_ms=elapsed_ms() - started,
            )
        return result

    @functools.wraps(original_reserve)
    def reserve(self, *args, **kwargs):
        started = elapsed_ms()
        record = active.get()
        try:
            result = original_reserve(self, *args, **kwargs)
            if record is not None:
                record.update(
                    granted_at_ms=elapsed_ms(),
                    reserved_prompt_tokens=result.prompt_tokens,
                    output_allowance_tokens=result.max_output_tokens,
                    total_reserved_tokens=result.token_reservation,
                )
            return result
        finally:
            if record is not None:
                record["reservation_acquisition_ms"] = elapsed_ms() - started

    @functools.wraps(original_success)
    def success(self, reservation, usage):
        result = original_success(self, reservation, usage)
        record = active.get()
        if record is not None:
            record["released_at_ms"] = elapsed_ms()
            record["usage"] = (
                usage.model_dump(mode="json") if usage is not None else None
            )
        return result

    @functools.wraps(original_failure)
    def failure(self, *args, **kwargs):
        result = original_failure(self, *args, **kwargs)
        record = active.get()
        if record is not None:
            record["released_at_ms"] = elapsed_ms()
        return result

    llm_type.invoke = invoke
    ledger_type.estimate_tokens = estimate
    ledger_type.reserve_llm_call = reserve
    ledger_type.record_success = success
    ledger_type.record_failure = failure

    def restore() -> None:
        llm_type.invoke = original_invoke
        ledger_type.estimate_tokens = original_estimate
        ledger_type.reserve_llm_call = original_reserve
        ledger_type.record_success = original_success
        ledger_type.record_failure = original_failure

    return restore
