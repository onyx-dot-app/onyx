"""Unified tracing setup for all providers (Braintrust, Langfuse, etc.)."""

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.configs.app_configs import LANGFUSE_HOST
from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
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
            logger.error(f"Failed to initialize Braintrust tracing: {e}")
    else:
        logger.info("Braintrust API key not provided, skipping Braintrust setup")

    # Setup Langfuse if configured
    if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
        try:
            _setup_langfuse()
            initialized_providers.append("langfuse")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse tracing: {e}")
    else:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")

    _initialized = True

    if initialized_providers:
        logger.notice(
            f"Tracing initialized with providers: {', '.join(initialized_providers)}"
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
    )

    add_trace_processor(LangfuseTracingProcessor(client=client))
