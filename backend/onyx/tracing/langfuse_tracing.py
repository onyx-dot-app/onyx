from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.utils.logger import setup_logger

logger = setup_logger()


def setup_langfuse_if_creds_available() -> None:
    # Check if Langfuse credentials are available
    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")
        return

    # Lazy imports to avoid loading when not needed
    from langfuse import get_client

    from onyx.tracing.framework import add_trace_processor
    from onyx.tracing.langfuse_tracing_processor import LangfuseTracingProcessor

    # Initialize Langfuse client
    client = get_client()

    # Add Langfuse processor to handle traces
    # This processor uses our internal trace IDs directly, ensuring they match
    add_trace_processor(LangfuseTracingProcessor(client=client))
