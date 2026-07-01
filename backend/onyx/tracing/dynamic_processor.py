"""Tracing processor that reflects the live (DB-or-env) provider config.

Registered once at startup; resolves the effective config on a short TTL and
rebuilds the Braintrust/Langfuse delegates when it changes, so connect/disconnect
applies without a restart. The delegate set is pinned per-trace so a config change
never disrupts an in-flight trace.
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
    import os

    import braintrust

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
    from onyx.tracing.masking import mask_sensitive_data

    # The Braintrust SDK reads BRAINTRUST_API_URL from the env; keep it in sync
    # (and cleared when unset) so a custom/self-hosted URL is honored.
    if config.api_url:
        os.environ["BRAINTRUST_API_URL"] = config.api_url
    else:
        os.environ.pop("BRAINTRUST_API_URL", None)

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

    # The Langfuse SDK reads LANGFUSE_HOST from the env in some paths; keep it in
    # sync (and cleared when no host is configured) to avoid a stale value.
    if config.host:
        os.environ["LANGFUSE_HOST"] = config.host
    else:
        os.environ.pop("LANGFUSE_HOST", None)

    client = Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        host=config.host or None,
        release=__version__,
    )
    return LangfuseTracingProcessor(client=client)


def build_delegates(config: EffectiveTracingConfig) -> list[TracingProcessor]:
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
        """Refresh the config (TTL-throttled unless ``force``) and rebuild delegates
        if it changed. All provider I/O happens off the lock."""
        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._fingerprint is not _UNSET
                and (now - self._last_checked) < self._ttl
            ):
                return None
            self._last_checked = now
            current_fingerprint = self._fingerprint

        config = resolve_effective_tracing_config()
        fingerprint = config.fingerprint()
        if fingerprint == current_fingerprint:
            return config

        # Build new delegates (imports + SDK client init + network I/O) off the lock.
        new_delegates = build_delegates(config)

        discard: list[TracingProcessor] | None = None
        with self._lock:
            if fingerprint == self._fingerprint:
                # Another thread already applied this exact config while we built.
                discard = new_delegates
            else:
                if self._delegates:
                    self._retiring.append(self._delegates)
                self._delegates = new_delegates
                self._fingerprint = fingerprint
            drained = self._collect_drained()

        if discard is not None:
            _forward(discard, "shutdown")
        for delegate_set in drained:
            _forward(delegate_set, "shutdown")

        logger.notice(
            "Tracing config applied with providers: %s",
            ", ".join(config.active_provider_names()) or "none",
        )
        return config

    def _collect_drained(self) -> list[list[TracingProcessor]]:
        """Remove and return retired sets no trace references. Caller holds the lock;
        the returned sets must be shut down outside it (shutdown can block)."""
        referenced = {id(d) for d in self._trace_delegates.values()}
        drained = [s for s in self._retiring if id(s) not in referenced]
        self._retiring = [s for s in self._retiring if id(s) in referenced]
        return drained

    def on_trace_start(self, trace: Trace) -> None:
        # Tracing must never disrupt the traced operation: a config-refresh
        # failure (e.g. DB unreachable) is logged and we keep the existing
        # delegates. Delegate callbacks themselves are guarded in `_forward`, so
        # a provider connection dropping mid-trace is caught and logged too.
        try:
            self.reconcile()
        except Exception as e:
            logger.error("Failed to refresh tracing config at trace start: %s", e)
        with self._lock:
            delegates = self._delegates
            self._trace_delegates[trace.trace_id] = delegates
        _forward(delegates, "on_trace_start", trace)

    def on_trace_end(self, trace: Trace) -> None:
        with self._lock:
            delegates = self._trace_delegates.pop(trace.trace_id, self._delegates)
        _forward(delegates, "on_trace_end", trace)
        with self._lock:
            drained = self._collect_drained()
        for delegate_set in drained:
            _forward(delegate_set, "shutdown")

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
            delegates = self._delegates + [p for s in self._retiring for p in s]
        _forward(delegates, "force_flush")

    def shutdown(self) -> None:
        with self._lock:
            delegates = self._delegates + [p for s in self._retiring for p in s]
            self._retiring = []
        _forward(delegates, "shutdown")
