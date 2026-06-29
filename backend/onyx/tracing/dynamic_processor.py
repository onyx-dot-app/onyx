"""A single tracing processor that reflects the live (DB-or-env) provider config.

Registered once at startup. It resolves the effective tracing config on a short
TTL and (re)builds the underlying Braintrust/Langfuse delegate processors when the
config changes — so an admin's connect/disconnect takes effect without a restart,
across every process that emits traces.

To avoid disrupting a trace that is already in flight when the config changes, the
delegate set is pinned per-trace at ``on_trace_start``: a trace's spans and its
``on_trace_end`` are always routed to the delegates it began with. Replaced
("retired") delegate sets are flushed immediately and shut down once their last
in-flight trace drains.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from onyx.configs.app_configs import TRACING_CONFIG_CACHE_TTL_SECONDS
from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace
from onyx.tracing.provider_config import BraintrustConfig
from onyx.tracing.provider_config import EffectiveTracingConfig
from onyx.tracing.provider_config import LangfuseConfig
from onyx.tracing.provider_config import resolve_effective_tracing_config
from onyx.utils.logger import setup_logger

logger = setup_logger()

_UNSET = object()


def _build_braintrust_processor(config: BraintrustConfig) -> TracingProcessor:
    import braintrust

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
    from onyx.tracing.masking import mask_sensitive_data

    braintrust_logger = braintrust.init_logger(
        project=config.project,
        api_key=config.api_key,
    )
    braintrust.set_masking_function(mask_sensitive_data)
    return BraintrustTracingProcessor(braintrust_logger)


def _build_langfuse_processor(config: LangfuseConfig) -> TracingProcessor:
    import os

    from langfuse import Langfuse

    from onyx import __version__
    from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor

    # Langfuse SDK reads LANGFUSE_HOST from the environment in some code paths.
    if config.host:
        os.environ["LANGFUSE_HOST"] = config.host

    client = Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        host=config.host or None,
        release=__version__,
    )
    return LangfuseTracingProcessor(client=client)


def build_delegates(config: EffectiveTracingConfig) -> list[TracingProcessor]:
    """Construct the provider processors for an effective config. Each provider is
    isolated: a failure building one does not prevent the other."""
    delegates: list[TracingProcessor] = []
    if config.braintrust:
        try:
            delegates.append(_build_braintrust_processor(config.braintrust))
        except Exception as e:
            logger.error("Failed to initialize Braintrust tracing: %s", e)
    if config.langfuse:
        try:
            delegates.append(_build_langfuse_processor(config.langfuse))
        except Exception as e:
            logger.error("Failed to initialize Langfuse tracing: %s", e)
    return delegates


def _forward(delegates: list[TracingProcessor], method: str, *args: Any) -> None:
    for processor in delegates:
        try:
            getattr(processor, method)(*args)
        except Exception as e:
            logger.error(
                "Error in trace processor %s during %s: %s", processor, method, e
            )


class DynamicTracingProcessor(TracingProcessor):
    def __init__(self, ttl_seconds: float = TRACING_CONFIG_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._fingerprint: object = _UNSET
        self._delegates: list[TracingProcessor] = []
        self._last_checked: float = 0.0
        # in-flight trace_id -> the delegate set captured at its start
        self._trace_delegates: dict[str, list[TracingProcessor]] = {}
        # delegate sets replaced by a reconfig, awaiting their in-flight traces to drain
        self._retiring: list[list[TracingProcessor]] = []

    def reconcile(self, force: bool = False) -> EffectiveTracingConfig | None:
        """Refresh the effective config (TTL-throttled unless ``force``) and rebuild
        delegates if it changed. Returns the resolved config when a check ran."""
        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._fingerprint is not _UNSET
                and (now - self._last_checked) < self._ttl
            ):
                return None
            self._last_checked = now

        config = resolve_effective_tracing_config()
        fingerprint = config.fingerprint()

        retired: list[TracingProcessor] | None = None
        with self._lock:
            if fingerprint == self._fingerprint:
                return config
            if self._delegates:
                retired = self._delegates
                self._retiring.append(retired)
            self._delegates = build_delegates(config)
            self._fingerprint = fingerprint

        if retired:
            # Flush immediately so buffered spans are sent; full shutdown waits until
            # the set's in-flight traces drain (see _reap_retired).
            _forward(retired, "force_flush")
            with self._lock:
                self._reap_retired()
        logger.notice(
            "Tracing config applied with providers: %s",
            ", ".join(config.active_provider_names()) or "none",
        )
        return config

    def _reap_retired(self) -> None:
        """Shut down retired delegate sets that no trace references anymore.
        Caller must hold ``self._lock``."""
        still_referenced = {id(d) for d in self._trace_delegates.values()}
        drained = [s for s in self._retiring if id(s) not in still_referenced]
        self._retiring = [s for s in self._retiring if id(s) in still_referenced]
        for delegate_set in drained:
            _forward(delegate_set, "shutdown")

    def on_trace_start(self, trace: Trace) -> None:
        self.reconcile()
        with self._lock:
            delegates = self._delegates
            self._trace_delegates[trace.trace_id] = delegates
        _forward(delegates, "on_trace_start", trace)

    def on_trace_end(self, trace: Trace) -> None:
        with self._lock:
            delegates = self._trace_delegates.pop(trace.trace_id, self._delegates)
        _forward(delegates, "on_trace_end", trace)
        with self._lock:
            self._reap_retired()

    def on_span_start(self, span: Span[Any]) -> None:
        with self._lock:
            delegates = self._trace_delegates.get(span.trace_id, self._delegates)
        _forward(delegates, "on_span_start", span)

    def on_span_end(self, span: Span[Any]) -> None:
        with self._lock:
            delegates = self._trace_delegates.get(span.trace_id, self._delegates)
        _forward(delegates, "on_span_end", span)

    def force_flush(self) -> None:
        with self._lock:
            delegates = list(self._delegates)
            retiring = [p for s in self._retiring for p in s]
        _forward(delegates + retiring, "force_flush")

    def shutdown(self) -> None:
        with self._lock:
            delegates = list(self._delegates)
            retiring = [p for s in self._retiring for p in s]
            self._retiring = []
        _forward(delegates + retiring, "shutdown")
