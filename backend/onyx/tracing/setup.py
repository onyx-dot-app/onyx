"""Unified tracing setup for all providers (Braintrust, Langfuse, etc.).

Registers a single :class:`DynamicTracingProcessor` that resolves the effective
(DB-backed, env-fallback) provider config at runtime, so admin connect/disconnect
takes effect without a restart. See ``onyx/tracing/provider_config.py`` and
``onyx/tracing/dynamic_processor.py``.
"""

from onyx.tracing.dynamic_processor import DynamicTracingProcessor
from onyx.tracing.framework import set_trace_processors
from onyx.utils.logger import setup_logger

logger = setup_logger()

_initialized = False
_dynamic_processor: DynamicTracingProcessor | None = None


def setup_tracing() -> list[str]:
    """Register the dynamic tracing processor and perform an initial config read.

    Idempotent: subsequent calls are no-ops (the registered processor refreshes its
    own config on a short TTL). Returns the provider names active at startup.
    """
    global _initialized, _dynamic_processor
    if _initialized:
        logger.debug("Tracing already initialized, skipping")
        return []

    _dynamic_processor = DynamicTracingProcessor()
    set_trace_processors([_dynamic_processor])
    config = _dynamic_processor.reconcile(force=True)
    _initialized = True

    initialized_providers = config.active_provider_names() if config else []
    if initialized_providers:
        logger.notice(
            "Tracing initialized with providers: %s", ", ".join(initialized_providers)
        )
    else:
        logger.info("No tracing providers configured")

    return initialized_providers
