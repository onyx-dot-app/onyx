"""Universal per-user usage recorder — buffers priced generation spans and
drains them to the per-user usage rollup off the LLM hot path."""

from __future__ import annotations

import queue
import threading
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.user_usage import USER_USAGE_BUCKET_SECONDS, record_user_usage
from onyx.llm.cost import compute_cost_cents
from onyx.tracing.flows import IMAGE_FLOWS
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace
from onyx.utils.datetime import get_window_start
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
    get_current_user_id,
)

logger = setup_logger()

_DEFAULT_FLUSH_INTERVAL_SECONDS = 2.0
# Drain early once this many records have queued up, regardless of interval.
_FLUSH_BATCH_SIZE = 200
# Bound the buffer so a DB slowdown/outage (producer outpacing the single drain
# thread) sheds load instead of growing memory unboundedly. Sized for a large
# burst; overflow drops the oldest-unqueued sample with a log, never blocks.
_MAX_QUEUE_SIZE = 100_000
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
    image_count: int
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
    def __init__(
        self, flush_interval_seconds: float = _DEFAULT_FLUSH_INTERVAL_SECONDS
    ) -> None:
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._flush_interval = flush_interval_seconds
        self._shutdown = threading.Event()
        # Serializes shutdown vs enqueue so no record lands after the sentinel.
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
                # Drop if shutdown started — drain won't see this record.
                if self._shutdown.is_set():
                    return
                try:
                    # Never block the LLM hot path: shed load if the buffer is
                    # full (drain thread stalled on a slow/unavailable DB).
                    self._queue.put_nowait(record)
                except queue.Full:
                    logger.warning(
                        "user-usage queue full (%d); dropping sample", _MAX_QUEUE_SIZE
                    )
        except Exception:
            logger.exception("UserUsageTracingProcessor.on_span_end failed; dropping")

    def _capture(self, span: Span[Any]) -> _UsageRecord | None:
        data = span.span_data
        if not isinstance(data, GenerationSpanData):
            return None

        model_config = data.model_config or {}
        flow = model_config.get("flow") or ""
        if not data.usage and flow not in IMAGE_FLOWS:
            return None

        user_id = get_current_user_id()
        if user_id is None:
            # No user id → skip (undercount, never wrong-user). Only chat
            # endpoints set the var today.
            return None

        model = data.model
        if not model:
            return None

        usage = data.usage or {}
        input_tokens = _usage_field(usage, "input_tokens", "prompt_tokens")
        output_tokens = _usage_field(usage, "output_tokens", "completion_tokens")
        cache_read_tokens = _usage_field(usage, "cache_read_input_tokens")
        provider = model_config.get("model_provider")

        window_start = get_window_start(
            datetime.now(timezone.utc), period_seconds=USER_USAGE_BUCKET_SECONDS
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
            image_count=data.image_count or 1,
            window_start=window_start,
        )

    def _drain_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=self._flush_interval)
            except queue.Empty:
                # Exit on shutdown even if the sentinel couldn't be enqueued
                # (queue was full) — don't rely solely on the sentinel.
                if self._shutdown.is_set():
                    return
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
        try:
            records_by_tenant: dict[str, list[_UsageRecord]] = defaultdict(list)
            for record in self._aggregate_batch(batch):
                records_by_tenant[record.tenant_id].append(record)

            for tenant_id, records in records_by_tenant.items():
                try:
                    self._write_tenant_batch(tenant_id, records)
                except Exception:
                    logger.exception(
                        "Failed to record usage batch for tenant %s; dropping samples",
                        tenant_id,
                    )
        finally:
            for _ in batch:
                self._queue.task_done()

    @staticmethod
    def _aggregate_batch(batch: list[_UsageRecord]) -> list[_UsageRecord]:
        aggregated: dict[
            tuple[str, str, str, str, str | None, datetime], _UsageRecord
        ] = {}
        for record in batch:
            key = (
                record.tenant_id,
                record.user_id,
                record.model,
                record.flow,
                record.provider,
                record.window_start,
            )
            current = aggregated.get(key)
            if current is None:
                aggregated[key] = record
                continue
            aggregated[key] = replace(
                current,
                input_tokens=current.input_tokens + record.input_tokens,
                output_tokens=current.output_tokens + record.output_tokens,
                cache_read_tokens=current.cache_read_tokens + record.cache_read_tokens,
                image_count=current.image_count + record.image_count,
            )
        return list(aggregated.values())

    def _write_tenant_batch(self, tenant_id: str, records: list[_UsageRecord]) -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                for record in records:
                    self._write_record(db_session, record)
                db_session.commit()
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    @staticmethod
    def _write_record(db_session: Session, record: _UsageRecord) -> None:
        non_cached_input = max(record.input_tokens - record.cache_read_tokens, 0)
        input_cost, output_cost = compute_cost_cents(
            record.model,
            record.provider,
            non_cached_input,
            record.output_tokens,
            cache_read_tokens=record.cache_read_tokens,
            flow=record.flow,
            image_count=record.image_count,
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
        # Lock: no enqueue after shutdown sentinel.
        with self._enqueue_lock:
            if self._shutdown.is_set():
                return
            self._shutdown.set()
        try:
            # Wake the drain thread now if there's room; if the queue is full,
            # the flag-check on its next get() timeout exits it. Never block here.
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:
            pass
        self._thread.join(timeout=10.0)
