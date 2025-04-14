from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import MainOutput
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.prompts.kg_prompts import OUTPUT_FORMAT_NO_EXAMPLES_PROMPT
from onyx.prompts.kg_prompts import OUTPUT_FORMAT_NO_OVERALL_ANSWER_PROMPT
from onyx.prompts.kg_prompts import OUTPUT_FORMAT_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def generate_answer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> MainOutput:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    state.entities_types_str
    introductory_answer = state.query_results_data_str
    state.reference_results
    search_tool = graph_config.tooling.search_tool
    if search_tool is None:
        raise ValueError("Search tool is not set")

    consolidated_research_object_results_str = (
        state.consolidated_research_object_results_str
    )

    question = graph_config.inputs.search_request.query

    output_format = state.output_format
    if state.reference_results:
        examples = (
            state.reference_results.citations
            or state.reference_results.general_entities
            or []
        )
        research_results = "\n".join([f"- {example}" for example in examples])
    elif consolidated_research_object_results_str:
        research_results = consolidated_research_object_results_str
    else:
        research_results = ""

    if research_results and introductory_answer:
        output_format_prompt = (
            OUTPUT_FORMAT_PROMPT.replace("---question---", question)
            .replace("---introductory_answer---", introductory_answer)
            .replace("---output_format---", str(output_format) if output_format else "")
            .replace("---research_results---", research_results)
        )

    elif not research_results and introductory_answer:
        output_format_prompt = (
            OUTPUT_FORMAT_NO_EXAMPLES_PROMPT.replace("---question---", question)
            .replace("---introductory_answer---", introductory_answer)
            .replace("---output_format---", str(output_format) if output_format else "")
        )
    elif research_results and not introductory_answer:
        output_format_prompt = (
            OUTPUT_FORMAT_NO_OVERALL_ANSWER_PROMPT.replace("---question---", question)
            .replace("---output_format---", str(output_format) if output_format else "")
            .replace("---research_results---", research_results)
        )
    else:
        raise ValueError("No research results or introductory answer provided")

    msg = [
        HumanMessage(
            content=output_format_prompt,
        )
    ]
    fast_llm = graph_config.tooling.fast_llm
    dispatch_timings: list[float] = []
    response: list[str] = []

    def stream_answer() -> list[str]:
        for message in fast_llm.stream(
            prompt=msg,
            timeout_override=30,
            max_tokens=1000,
        ):
            # TODO: in principle, the answer here COULD contain images, but we don't support that yet
            content = message.content
            if not isinstance(content, str):
                raise ValueError(
                    f"Expected content to be a string, but got {type(content)}"
                )
            start_stream_token = datetime.now()
            write_custom_event(
                "initial_agent_answer",
                AgentAnswerPiece(
                    answer_piece=content,
                    level=0,
                    level_question_num=0,
                    answer_type="agent_level_answer",
                ),
                writer,
            )
            # logger.debug(f"Answer piece: {content}")
            end_stream_token = datetime.now()
            dispatch_timings.append(
                (end_stream_token - start_stream_token).microseconds
            )
            response.append(content)
        return response

    try:
        response = run_with_timeout(
            30,
            stream_answer,
        )

    except Exception as e:
        raise ValueError(f"Could not generate the answer. Error {e}")

    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_ANSWER,
        level=0,
        level_question_num=0,
    )
    write_custom_event("stream_finished", stop_event, writer)

    dispatch_main_answer_stop_info(0, writer)

    return MainOutput(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="query completed",
                node_start_time=node_start_time,
            )
        ],
    )
