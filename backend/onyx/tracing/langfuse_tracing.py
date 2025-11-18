from typing import cast

from openinference.instrumentation import OITracer
from openinference.instrumentation import TraceConfig
from openinference.instrumentation.openai_agents.version import __version__
from opentelemetry import trace as trace_api

from onyx.configs.app_configs import LANGFUSE_HOST
from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.tracing import set_trace_processors
from onyx.tracing.openinference_tracing_processor import OpenInferenceTracingProcessor
from onyx.utils.logger import setup_logger

logger = setup_logger()


def setup_langfuse_if_creds_available() -> None:
    # Check if Langfuse credentials are available
    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")
        return

    import nest_asyncio  # type: ignore
    from langfuse import get_client

    nest_asyncio.apply()
    config = TraceConfig()
    tracer_provider = trace_api.get_tracer_provider()
    tracer = OITracer(
        trace_api.get_tracer(__name__, __version__, tracer_provider),
        config=config,
    )

    set_trace_processors(
        [OpenInferenceTracingProcessor(cast(trace_api.Tracer, tracer))]
    )
    langfuse = get_client()

    try:
        if langfuse.auth_check():
            logger.notice(f"Langfuse authentication successful (host: {LANGFUSE_HOST})")
        else:
            logger.warning("Langfuse authentication failed")
    except Exception as e:
        logger.error(f"Error setting up Langfuse: {e}")
