"""Unified tracing setup for all providers (Braintrust, Langfuse, etc.)."""

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.configs.app_configs import LANGFUSE_HOST
from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.configs.app_configs import USER_USAGE_TRACKING_ENABLED
from onyx.utils.logger import setup_logger

logger = setup_logger()

_initialized = False


def setup_tracing() -> list[str]:
    """Initialize all configured tracing providers.

    Returns a list of provider names that were successfully initialized.
    Uses add_trace_processor() to ADD processors rather than replacing them,
    allowing multiple providers to receive trace events simultaneously.

    This function is idempotent - calling it multiple times will only
    initialize providers once.
    """
    global _initialized
    if _initialized:
        logger.debug("Tracing already initialized, skipping")
        return []

    initialized_providers: list[str] = []

    # Setup Braintrust if configured
    if BRAINTRUST_API_KEY:
        try:
            _setup_braintrust()
            initialized_providers.append("braintrust")
        except Exception as e:
            logger.error("Failed to initialize Braintrust tracing: %s", e)
    else:
        logger.info("Braintrust API key not provided, skipping Braintrust setup")

    # Setup Langfuse if configured
    if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
        try:
            _setup_langfuse()
            initialized_providers.append("langfuse")
        except Exception as e:
            logger.error("Failed to initialize Langfuse tracing: %s", e)
    else:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")

    # Per-user usage recorder — independent of external tracing backends.
    if USER_USAGE_TRACKING_ENABLED:
        try:
            _setup_user_usage_tracking()
            initialized_providers.append("user_usage")
        except Exception as e:
            logger.error("Failed to initialize user usage tracking: %s", e)
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


def _setup_braintrust() -> None:
    """Initialize Braintrust tracing."""
    import braintrust

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
    from onyx.tracing.framework import add_trace_processor
    from onyx.tracing.masking import mask_sensitive_data

    braintrust_logger = braintrust.init_logger(
        project=BRAINTRUST_PROJECT,
        api_key=BRAINTRUST_API_KEY,
    )
    braintrust.set_masking_function(mask_sensitive_data)
    add_trace_processor(BraintrustTracingProcessor(braintrust_logger))


def _setup_langfuse() -> None:
    """Initialize Langfuse tracing using the native Langfuse SDK."""
    import os

    from langfuse import Langfuse

    from onyx import __version__
    from onyx.tracing.framework import add_trace_processor
    from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor

    # Set LANGFUSE_HOST env var if configured (Langfuse SDK reads this automatically)
    if LANGFUSE_HOST:
        os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST

    # Initialize Langfuse client with credentials
    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        host=LANGFUSE_HOST if LANGFUSE_HOST else None,
        release=__version__,
    )

    add_trace_processor(LangfuseTracingProcessor(client=client))


_user_usage_processor: object | None = None


def _setup_user_usage_tracking() -> None:
    """Register the per-user usage recording processor."""
    global _user_usage_processor
    from onyx.tracing.framework import add_trace_processor
    from onyx.tracing.processors.user_usage_processor import UserUsageTracingProcessor

    processor = UserUsageTracingProcessor()
    _user_usage_processor = processor
    add_trace_processor(processor)


def shutdown_tracing() -> None:
    """Flush buffered usage to the DB on shutdown. Call before disposing the DB
    engines (the drain thread writes through them) so queued records aren't lost."""
    from onyx.tracing.processors.user_usage_processor import UserUsageTracingProcessor

    if isinstance(_user_usage_processor, UserUsageTracingProcessor):
        try:
            _user_usage_processor.shutdown()
        except Exception:
            logger.exception("Failed to flush user usage on shutdown")
