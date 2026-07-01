"""Registers the DynamicTracingProcessor, which resolves the live (DB-or-env)
provider config at runtime so config changes apply without a restart."""

from onyx.tracing.dynamic_processor import DynamicTracingProcessor
from onyx.tracing.framework import set_trace_processors
from onyx.utils.logger import setup_logger

logger = setup_logger()

_initialized = False
_dynamic_processor: DynamicTracingProcessor | None = None


def setup_tracing() -> list[str]:
    """Register the dynamic tracing processor and do an initial config read.
    Idempotent; returns the provider names active at startup."""
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
