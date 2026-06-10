"""Universal per-user usage recorder — buffers priced generation spans and
drains them to the per-user usage rollup off the LLM hot path."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.user_usage import get_window_start
from onyx.db.user_usage import record_user_usage
from onyx.db.user_usage import USAGE_PERIOD_HOURS
from onyx.llm.cost import compute_cost_cents
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id
from shared_configs.contextvars import get_current_user_id

logger = setup_logger()

_DEFAULT_FLUSH_INTERVAL_SECONDS = 2.0
# Drain early once this many records have queued up, regardless of interval.
_FLUSH_BATCH_SIZE = 200
# Sentinel pushed on shutdown to wake the drain thread immediately.
_SHUTDOWN = object()


@dataclass(frozen=True)
class _UsageRecord:
    """Everything needed to write one ledger row, captured at span-end while the
    request contextvars are still valid (the drain thread has none)."""

    tenant_id: str
    user_id: str
    model: str
    flow: str
    provider: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    window_start: datetime


def _usage_field(usage: dict[str, Any], *names: str) -> int:
    """First present token field among `names`, coerced to int. Mirrors the
    prompt/completion vs input/output aliasing from llm_utils._build_usage_dict."""
    for name in names:
        value = usage.get(name)
        if value is not None:
            return int(value)
    return 0


class UserUsageTracingProcessor(TracingProcessor):
    """Records every priced generation span into the per-user usage ledger.

    on_span_end captures the sample synchronously (contextvars are only valid
    there) and enqueues it; a daemon thread drains the queue to Postgres so the
    streaming/LLM path is never blocked by a DB write. Cost is computed in the
    drain thread under the captured tenant's session + tenant context."""

    def __init__(
        self, flush_interval_seconds: float = _DEFAULT_FLUSH_INTERVAL_SECONDS
    ) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._flush_interval = flush_interval_seconds
        self._shutdown = threading.Event()
        # Serializes the shutdown flag against enqueues so a record can't slip in
        # after the _SHUTDOWN sentinel — every record is enqueued before it or
        # dropped, never lost to a drained-and-exited thread.
        self._enqueue_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._drain_loop, name="user-usage-recorder", daemon=True
        )
        self._thread.start()

    def on_span_end(self, span: Span[Any]) -> None:
        # Never propagate into the span/LLM path.
        try:
            record = self._capture(span)
            if record is None:
                return
            with self._enqueue_lock:
                # Drop once shutting down — the sentinel is or will be the last
                # item, so the drain thread won't pick this up.
                if self._shutdown.is_set():
                    return
                self._queue.put(record)
        except Exception:
            logger.exception("UserUsageTracingProcessor.on_span_end failed; dropping")

    def _capture(self, span: Span[Any]) -> _UsageRecord | None:
        data = span.span_data
        if not isinstance(data, GenerationSpanData) or not data.usage:
            return None

        user_id = get_current_user_id()
        if user_id is None:
            # Background worker / no request — nothing to attribute.
            return None

        model = data.model
        if not model:
            return None

        usage = data.usage
        input_tokens = _usage_field(usage, "input_tokens", "prompt_tokens")
        output_tokens = _usage_field(usage, "output_tokens", "completion_tokens")
        cache_read_tokens = _usage_field(usage, "cache_read_input_tokens")

        model_config = data.model_config or {}
        flow = model_config.get("flow") or ""
        provider = model_config.get("model_provider")

        window_start = get_window_start(
            datetime.now(timezone.utc), period_hours=USAGE_PERIOD_HOURS
        )

        return _UsageRecord(
            tenant_id=get_current_tenant_id(),
            user_id=user_id,
            model=model,
            flow=flow,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            window_start=window_start,
        )

    def _drain_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                continue

            if item is _SHUTDOWN:
                self._queue.task_done()
                return

            batch = [item]
            while len(batch) < _FLUSH_BATCH_SIZE:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _SHUTDOWN:
                    self._flush_batch(batch)
                    self._queue.task_done()  # the SHUTDOWN sentinel
                    return
                batch.append(nxt)

            self._flush_batch(batch)

    def _flush_batch(self, batch: list[_UsageRecord]) -> None:
        for record in batch:
            try:
                self._write(record)
            except Exception:
                logger.exception(
                    "Failed to record user usage (user=%s model=%s); dropping sample",
                    record.user_id,
                    record.model,
                )
            finally:
                # task_done per real record so force_flush()'s join() unblocks
                # even when the write raised.
                self._queue.task_done()

    def _write(self, record: _UsageRecord) -> None:
        # The drain thread has no request contextvars; restore the captured
        # tenant so the cost-override lookup resolves the right schema.
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(record.tenant_id)
        try:
            with get_session_with_tenant(tenant_id=record.tenant_id) as db_session:
                # The span's input_tokens is the litellm prompt total, which
                # already includes cache reads; compute_cost_cents expects the
                # NON-cached count and adds cache reads back at the cache rate.
                # Subtract here to avoid pricing cache reads twice. The ledger
                # column keeps the full input_tokens for token reporting.
                non_cached_input = max(
                    record.input_tokens - record.cache_read_tokens, 0
                )
                input_cost, output_cost = compute_cost_cents(
                    record.model,
                    record.provider,
                    non_cached_input,
                    record.output_tokens,
                    cache_read_tokens=record.cache_read_tokens,
                    flow=record.flow,
                    db_session=db_session,
                )
                record_user_usage(
                    db_session,
                    user_id=record.user_id,
                    model=record.model,
                    flow=record.flow,
                    provider=record.provider,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cache_read_tokens=record.cache_read_tokens,
                    cost_cents=input_cost + output_cost,
                    window_start=record.window_start,
                )
                db_session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    # --- TracingProcessor interface (non-generation events are no-ops) ---

    def on_trace_start(self, trace: Trace) -> None:
        pass

    def on_trace_end(self, trace: Trace) -> None:
        pass

    def on_span_start(self, span: Span[Any]) -> None:
        pass

    def force_flush(self) -> None:
        """Block until every queued record has been processed (written or dropped)."""
        if not self._thread.is_alive():
            return
        self._queue.join()

    def shutdown(self) -> None:
        # Set the flag under the lock so any concurrent on_span_end either
        # enqueues before the sentinel or sees the flag and drops — no record
        # lands after _SHUTDOWN.
        with self._enqueue_lock:
            if self._shutdown.is_set():
                return
            self._shutdown.set()
        self._queue.put(_SHUTDOWN)
        self._thread.join(timeout=10.0)
