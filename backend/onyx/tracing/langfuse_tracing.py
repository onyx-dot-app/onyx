import os

from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.utils.logger import setup_logger

logger = setup_logger()


def setup_langfuse_if_creds_available() -> None:
    # Check if Langfuse credentials are available
    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        logger.info("Langfuse credentials not provided, skipping Langfuse setup")
        return

    import nest_asyncio  # type: ignore

    nest_asyncio.apply()

    from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

    OpenAIAgentsInstrumentor().instrument()
    langfuse_host = (
        os.environ.get("LANGFUSE_HOST")
        or os.environ.get("LANGFUSE_BASE_URL")
        or "https://cloud.langfuse.com"
    )
    logger.info(
        "Langfuse tracing enabled with host=%s pk_present=%s sk_present=%s",
        langfuse_host,
        bool(LANGFUSE_PUBLIC_KEY),
        bool(LANGFUSE_SECRET_KEY),
    )
    # TODO: this is how the tracing processor will look once we migrate over to new framework
    # config = TraceConfig()
    # tracer_provider = trace_api.get_tracer_provider()
    # tracer = OITracer(
    #     trace_api.get_tracer(__name__, __version__, tracer_provider),
    #     config=config,
    # )

    # set_trace_processors(
    #     [OpenInferenceTracingProcessor(cast(trace_api.Tracer, tracer))]
    # )
