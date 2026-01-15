from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.utils.logger import setup_logger

logger = setup_logger()


def setup_langfuse_if_creds_available() -> None:
    # Check if Langfuse credentials are available
    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")
        return

    # Lazy imports to avoid loading OpenTelemetry/OpenInference when not needed
    from typing import cast

    import nest_asyncio  # type: ignore
    from langfuse import get_client
    from openinference.instrumentation import OITracer
    from openinference.instrumentation import TraceConfig
    from opentelemetry import trace as trace_api

    from onyx.tracing.framework import set_trace_processors
    from onyx.tracing.openinference_tracing_processor import (
        OpenInferenceTracingProcessor,
    )

    nest_asyncio.apply()
    config = TraceConfig()
    tracer_provider = trace_api.get_tracer_provider()
    tracer = OITracer(
        trace_api.get_tracer(__name__, tracer_provider=tracer_provider),
        config=config,
    )

    set_trace_processors(
        [OpenInferenceTracingProcessor(cast(trace_api.Tracer, tracer))]
    )
    # This is poorly named -- it actually is a get or create client for langfuse.
    # Langfuse with silently fail without this function call.
    _ = get_client()
