from onyx.configs.app_configs import LANGFUSE_ENABLED
from onyx.configs.app_configs import LANGFUSE_HOST
from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.utils.logger import setup_logger

logger = setup_logger()


def setup_langfuse_if_creds_available() -> None:
    # Check if Langfuse is enabled and credentials are available
    if not LANGFUSE_ENABLED:
        logger.info("Langfuse tracing is disabled")
        return

    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        logger.warning(
            "Langfuse is enabled but credentials are missing. Skipping Langfuse setup."
        )
        return

    import nest_asyncio
    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    from langfuse import get_client

    nest_asyncio.apply()
    OpenAIAgentsInstrumentor().instrument()
    langfuse = get_client()
    try:
        if langfuse.auth_check():
            logger.notice(f"Langfuse authentication successful (host: {LANGFUSE_HOST})")
        else:
            logger.warning("Langfuse authentication failed")
    except Exception as e:
        logger.error(f"Error setting up Langfuse: {e}")
