from collections.abc import Iterable
from typing import cast

from langchain_core.runnables.schema import CustomStreamEvent
from langchain_core.runnables.schema import StreamEvent
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
    callbacks: list[CallbackHandler] = []
    if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
        callbacks.append(CallbackHandler())
    for event in compiled_graph.stream(
        stream_mode="custom",
        input=graph_input,
        config={
            "metadata": {"config": config, "thread_id": str(message_id)},
            "callbacks": callbacks,  # type: ignore
        },
    ):
        yield cast(CustomStreamEvent, event)


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
