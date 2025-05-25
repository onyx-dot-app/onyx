from collections.abc import Iterable
from datetime import datetime
from typing import cast

from langchain_core.runnables.schema import CustomStreamEvent
from langchain_core.runnables.schema import StreamEvent
from langgraph.graph.state import CompiledStateGraph

from onyx.agents.agent_search.basic.graph_builder import basic_graph_builder
from onyx.agents.agent_search.basic.states import BasicInput
from onyx.agents.agent_search.dc_search_analysis.graph_builder import (
    divide_and_conquer_graph_builder,
)
from onyx.agents.agent_search.dc_search_analysis.states import MainInput as DCMainInput
from onyx.agents.agent_search.deep_search.main.graph_builder import (
    agent_search_graph_builder as agent_search_graph_builder,
)
from onyx.agents.agent_search.deep_search.main.states import (
    MainInput as MainInput,
)
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.kb_search.states import MainInput as KBMainInput
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import get_test_config
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import AnswerPacket
from onyx.chat.models import AnswerStream
from onyx.chat.models import ExtendedToolResponse
from onyx.chat.models import RefinedAnswerImprovement
from onyx.chat.models import StreamingError
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import SubQueryPiece
from onyx.chat.models import SubQuestionPiece
from onyx.chat.models import ToolResponse
from onyx.context.search.models import SearchRequest
from onyx.db.engine import get_session_context_manager
from onyx.llm.factory import get_default_llms
from onyx.tools.tool_runner import ToolCallKickoff
from onyx.utils.logger import setup_logger


logger = setup_logger()

_COMPILED_GRAPH: CompiledStateGraph | None = None


def _parse_agent_event(
    event: StreamEvent,
) -> AnswerPacket | None:
    """
    Parse the event into a typed object.
    Return None if we are not interested in the event.
    """
    event_type = event["event"]

    # We always just yield the event data, but this piece is useful for two development reasons:
    # 1. It's a list of the names of every place we dispatch a custom event
    # 2. We maintain the intended types yielded by each event
    if event_type == "on_custom_event":
        if event["name"] == "decomp_qs":
            return cast(SubQuestionPiece, event["data"])
        elif event["name"] == "subqueries":
            return cast(SubQueryPiece, event["data"])
        elif event["name"] == "sub_answers":
            return cast(AgentAnswerPiece, event["data"])
        elif event["name"] == "stream_finished":
            return cast(StreamStopInfo, event["data"])
        elif event["name"] == "initial_agent_answer":
            return cast(AgentAnswerPiece, event["data"])
        elif event["name"] == "refined_agent_answer":
            return cast(AgentAnswerPiece, event["data"])
        elif event["name"] == "start_refined_answer_creation":
            return cast(ToolCallKickoff, event["data"])
        elif event["name"] == "tool_response":
            return cast(ToolResponse, event["data"])
        elif event["name"] == "basic_response":
            return cast(AnswerPacket, event["data"])
        elif event["name"] == "refined_answer_improvement":
            return cast(RefinedAnswerImprovement, event["data"])
        elif event["name"] == "refined_sub_question_creation_error":
            return cast(StreamingError, event["data"])
        else:
            logger.error(f"Unknown event name: {event['name']}")
            return None

    logger.error(f"Unknown event type: {event_type}")
    return None


def manage_sync_streaming(
    compiled_graph: CompiledStateGraph,
    config: GraphConfig,
    graph_input: BasicInput | MainInput | DCMainInput | KBMainInput,
) -> Iterable[StreamEvent]:
    message_id = config.persistence.message_id if config.persistence else None
    for event in compiled_graph.stream(
        stream_mode="custom",
        input=graph_input,
        config={"metadata": {"config": config, "thread_id": str(message_id)}},
    ):
        yield cast(CustomStreamEvent, event)


def run_graph(
    compiled_graph: CompiledStateGraph,
    config: GraphConfig,
    input: BasicInput | MainInput | DCMainInput | KBMainInput,
) -> AnswerStream:

    for event in manage_sync_streaming(
        compiled_graph=compiled_graph, config=config, graph_input=input
    ):
        if not (parsed_object := _parse_agent_event(event)):
            continue

        yield parsed_object


# It doesn't actually take very long to load the graph, but we'd rather
# not compile it again on every request.
def load_compiled_graph() -> CompiledStateGraph:
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        graph = agent_search_graph_builder()
        _COMPILED_GRAPH = graph.compile()
    return _COMPILED_GRAPH


def run_agent_search_graph(
    config: GraphConfig,
) -> AnswerStream:
    compiled_graph = load_compiled_graph()

    input = MainInput(log_messages=[])
    # Agent search is not a Tool per se, but this is helpful for the frontend
    yield ToolCallKickoff(
        tool_name="agent_search_0",
        tool_args={"query": config.inputs.prompt_builder.raw_user_query},
    )
    yield from run_graph(compiled_graph, config, input)


def run_basic_graph(
    config: GraphConfig,
) -> AnswerStream:
    graph = basic_graph_builder()
    compiled_graph = graph.compile()
    input = BasicInput(unused=True)
    return run_graph(compiled_graph, config, input)


def run_kb_graph(
    config: GraphConfig,
) -> AnswerStream:
    graph = kb_graph_builder()
    compiled_graph = graph.compile()
    input = KBMainInput(log_messages=[])

    yield ToolCallKickoff(
        tool_name="agent_search_0",
        tool_args={"query": config.inputs.prompt_builder.raw_user_query},
    )

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


if __name__ == "__main__":
    for _ in range(1):
        query_start_time = datetime.now()
        logger.debug(f"Start at {query_start_time}")
        graph = agent_search_graph_builder()
        compiled_graph = graph.compile()
        query_end_time = datetime.now()
        logger.debug(f"Graph compiled in {query_end_time - query_start_time} seconds")
        primary_llm, fast_llm = get_default_llms()
        search_request = SearchRequest(
            # query="what can you do with gitlab?",
            # query="What are the guiding principles behind the development of cockroachDB",
            # query="What are the temperatures in Munich, Hawaii, and New York?",
            # query="When was Washington born?",
            # query="What is Onyx?",
            # query="What is the difference between astronomy and astrology?",
            query="Do a search to tell me what is the difference between astronomy and astrology?",
        )

        with get_session_context_manager() as db_session:
            config = get_test_config(db_session, primary_llm, fast_llm, search_request)
            assert (
                config.persistence is not None
            ), "set a chat session id to run this test"

            # search_request.persona = get_persona_by_id(1, None, db_session)
            # config.perform_initial_search_path_decision = False
            config.behavior.perform_initial_search_decomposition = True
            input = MainInput(log_messages=[])

            tool_responses: list = []
            for output in run_graph(compiled_graph, config, input):
                if isinstance(output, ToolCallKickoff):
                    pass
                elif isinstance(output, ExtendedToolResponse):
                    tool_responses.append(output.response)
                    logger.info(
                        f"   ---- ET {output.level} - {output.level_question_num} |  "
                    )
                elif isinstance(output, SubQueryPiece):
                    logger.info(
                        f"Sq {output.level} - {output.level_question_num} - {output.sub_query} | "
                    )
                elif isinstance(output, SubQuestionPiece):
                    logger.info(
                        f"SQ {output.level} - {output.level_question_num} - {output.sub_question} | "
                    )
                elif (
                    isinstance(output, AgentAnswerPiece)
                    and output.answer_type == "agent_sub_answer"
                ):
                    logger.info(
                        f"   ---- SA {output.level} - {output.level_question_num} {output.answer_piece} | "
                    )
                elif (
                    isinstance(output, AgentAnswerPiece)
                    and output.answer_type == "agent_level_answer"
                ):
                    logger.info(
                        f"   ---------- FA {output.level} - {output.level_question_num}  {output.answer_piece} | "
                    )
                elif isinstance(output, RefinedAnswerImprovement):
                    logger.info(
                        f"   ---------- RE {output.refined_answer_improvement} | "
                    )
