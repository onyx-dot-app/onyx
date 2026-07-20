"""Registers the DynamicTracingProcessor, which resolves the live (DB-or-env)
provider config at runtime so config changes apply without a restart."""

from onyx.configs.app_configs import USER_USAGE_TRACKING_ENABLED
from onyx.tracing.dynamic_processor import DynamicTracingProcessor
from onyx.tracing.framework import add_trace_processor
from onyx.tracing.framework import set_trace_processors
from onyx.utils.logger import setup_logger

logger = setup_logger()

_initialized = False
_dynamic_processor: DynamicTracingProcessor | None = None
_user_usage_processor: object | None = None


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

    initialized_providers = config.active_provider_names() if config else []

    # Per-user usage recorder — independent of external tracing backends.
    # Registered after set_trace_processors so it isn't wiped by the replace.
    if USER_USAGE_TRACKING_ENABLED:
        _setup_user_usage_tracking()
        initialized_providers.append("user_usage")
    else:
        logger.info("User usage tracking disabled, skipping")

    _initialized = True

    if initialized_providers:
        logger.notice(
            "Tracing initialized with providers: %s", ", ".join(initialized_providers)
        )
    else:
        logger.info("No tracing providers configured")

    return initialized_providers


def _setup_user_usage_tracking() -> None:
    """Register the per-user usage recording processor."""
    global _user_usage_processor
    from onyx.tracing.processors.user_usage_processor import UserUsageTracingProcessor

    processor = UserUsageTracingProcessor()
    _user_usage_processor = processor
    add_trace_processor(processor)


def shutdown_tracing() -> None:
    """Flush buffered usage to the DB on shutdown. Call before disposing the DB
    engines (the drain thread writes through them) so queued records aren't lost."""
    global _initialized, _dynamic_processor, _user_usage_processor

    from onyx.tracing.processors.user_usage_processor import UserUsageTracingProcessor

    if isinstance(_user_usage_processor, UserUsageTracingProcessor):
        try:
            _user_usage_processor.shutdown()
        except Exception:
            logger.exception("Failed to flush user usage on shutdown")
    if _dynamic_processor is not None:
        try:
            _dynamic_processor.shutdown()
        except Exception:
            logger.exception("Failed to shut down tracing providers")

    set_trace_processors([])
    _user_usage_processor = None
    _dynamic_processor = None
    _initialized = False
