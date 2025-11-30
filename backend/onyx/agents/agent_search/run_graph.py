import os
from collections.abc import Iterable
from typing import cast

from langchain_core.runnables.schema import CustomStreamEvent
from langchain_core.runnables.schema import StreamEvent
from langfuse import Langfuse

try:
    # Prefer the newer SDK path
    from langfuse.callback import CallbackHandler
except ImportError:
    # Fallback for older SDKs
    from langfuse.langchain import CallbackHandler
from langgraph.graph.state import CompiledStateGraph

from onyx.agents.agent_search.dc_search_analysis.graph_builder import (
    divide_and_conquer_graph_builder,
)
from onyx.agents.agent_search.dc_search_analysis.states import MainInput as DCMainInput
from onyx.agents.agent_search.dr.graph_builder import dr_graph_builder
from onyx.agents.agent_search.dr.states import MainInput as DRMainInput
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.kb_search.states import MainInput as KBMainInput
from onyx.agents.agent_search.models import GraphConfig
from onyx.chat.models import AnswerStream
from onyx.configs.app_configs import LANGFUSE_PUBLIC_KEY
from onyx.configs.app_configs import LANGFUSE_SECRET_KEY
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.utils.logger import setup_logger


logger = setup_logger()
GraphInput = DCMainInput | KBMainInput | DRMainInput


def manage_sync_streaming(
    compiled_graph: CompiledStateGraph,
    config: GraphConfig,
    graph_input: GraphInput,
) -> Iterable[StreamEvent]:
    message_id = config.persistence.message_id if config.persistence else None
    logger.info("manage_sync_streaming start thread_id=%s", message_id)
    callbacks: list[CallbackHandler] = []
    langfuse_client: Langfuse | None = None
    langfuse_trace = None
    langfuse_host = (
        os.environ.get("LANGFUSE_HOST")
        or os.environ.get("LANGFUSE_BASE_URL")
        or "https://cloud.langfuse.com"
    )
    if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
        try:
            langfuse_client = Langfuse(
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
                host=langfuse_host,
            )
            trace_id = str(message_id) if message_id is not None else None
            try:
                langfuse_trace = langfuse_client.trace(
                    id=trace_id,
                    name="agent-search",
                    input=getattr(graph_input, "question", None)
                    or getattr(graph_input, "log_messages", None),
                    metadata={"thread_id": message_id},
                )
                logger.info(
                    "Langfuse trace created thread_id=%s trace_id=%s host=%s",
                    message_id,
                    trace_id,
                    langfuse_host,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create Langfuse trace thread_id=%s: %s",
                    message_id,
                    exc,
                )
            try:
                callbacks.append(
                    CallbackHandler(langfuse_client=langfuse_client)
                )  # type: ignore[arg-type]
            except TypeError:
                callbacks.append(
                    CallbackHandler()
                )  # pragma: no cover - fallback for older signature
            logger.info(
                "Langfuse callback enabled for thread_id=%s host=%s callback_class=%s",
                message_id,
                langfuse_host,
                callbacks[-1].__class__.__name__,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Failed to initialize Langfuse callback for thread_id=%s: %s",
                message_id,
                exc,
            )
    else:
        logger.info("Langfuse callback disabled; missing credentials")
    if not callbacks:
        logger.debug(
            "No Langfuse callbacks attached for thread_id=%s; callbacks list empty",
            message_id,
        )
    events_emitted = 0
    try:
        for event in compiled_graph.stream(
            stream_mode="custom",
            input=graph_input,
            config={
                "metadata": {"config": config, "thread_id": str(message_id)},
                "callbacks": callbacks,  # type: ignore
            },
        ):
            events_emitted += 1
            yield cast(CustomStreamEvent, event)
    finally:
        logger.info(
            "manage_sync_streaming end thread_id=%s events=%s callbacks=%s trace_created=%s",
            message_id,
            events_emitted,
            bool(callbacks),
            bool(langfuse_trace),
        )
        if langfuse_trace:
            try:
                langfuse_trace.update(output="completed")
            except Exception as exc:
                logger.warning(
                    "Failed to update Langfuse trace thread_id=%s: %s",
                    message_id,
                    exc,
                )
        if langfuse_client:
            try:
                langfuse_client.flush()
            except Exception as exc:
                logger.warning(
                    "Failed to flush Langfuse client thread_id=%s: %s",
                    message_id,
                    exc,
                )


def run_graph(
    compiled_graph: CompiledStateGraph,
    config: GraphConfig,
    input: GraphInput,
) -> AnswerStream:

    for event in manage_sync_streaming(
        compiled_graph=compiled_graph, config=config, graph_input=input
    ):

        yield cast(Packet, event["data"])


def run_kb_graph(
    config: GraphConfig,
) -> AnswerStream:
    graph = kb_graph_builder()
    compiled_graph = graph.compile()
    input = KBMainInput(
        log_messages=[], question=config.inputs.prompt_builder.raw_user_query
    )

    yield from run_graph(compiled_graph, config, input)


def run_dr_graph(
    config: GraphConfig,
) -> AnswerStream:
    graph = dr_graph_builder()
    compiled_graph = graph.compile()
    input = DRMainInput(log_messages=[])

    yield from run_graph(compiled_graph, config, input)


def run_dc_graph(
    config: GraphConfig,
) -> AnswerStream:
    graph = divide_and_conquer_graph_builder()
    compiled_graph = graph.compile()
    input = DCMainInput(log_messages=[])
    config.inputs.prompt_builder.raw_user_query = (
        config.inputs.prompt_builder.raw_user_query.strip()
    )
    return run_graph(compiled_graph, config, input)
