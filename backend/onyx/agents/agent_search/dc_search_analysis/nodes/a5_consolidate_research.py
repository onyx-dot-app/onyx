from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dc_search_analysis.ops import extract_section
from onyx.agents.agent_search.dc_search_analysis.states import MainState
from onyx.agents.agent_search.dc_search_analysis.states import ResearchUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.prompts.agents.dc_prompts import DC_FORMATTING_NO_BASE_DATA_PROMPT
from onyx.prompts.agents.dc_prompts import DC_FORMATTING_WITH_BASE_DATA_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def consolidate_research(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ResearchUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    graph_config.inputs.search_request.query

    search_tool = graph_config.tooling.search_tool

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=" generating the answer\n\n\n",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    if search_tool is None or graph_config.inputs.search_request.persona is None:
        raise ValueError("Search tool and persona must be provided for DivCon search")

    # Populate prompt
    instructions = graph_config.inputs.search_request.persona.prompts[0].system_prompt

    try:
        agent_5_instructions = extract_section(
            instructions, "Agent Step 5:", "Agent End"
        )
        if agent_5_instructions is None:
            raise ValueError("Agent 5 instructions not found")
        agent_5_base_data = extract_section(instructions, "|Start Data|", "|End Data|")
        agent_5_task = extract_section(
            agent_5_instructions, "Task:", "Independent Research Sources:"
        )
        if agent_5_task is None:
            raise ValueError("Agent 5 task not found")
        agent_5_output_objective = extract_section(
            agent_5_instructions, "Output Objective:"
        )
        if agent_5_output_objective is None:
            raise ValueError("Agent 5 output objective not found")
    except ValueError as e:
        raise ValueError(
            f"Instructions for Agent Step 5 were not properly formatted: {e}"
        )

    research_result_list = []

    if agent_5_task.strip() == "*concatenate*":
        object_research_results = state.object_research_results

        for object_research_result in object_research_results:
            object = object_research_result["object"]
            research_result = object_research_result["research_result"]
            research_result_list.append(f"Object: {object}\n\n{research_result}")

        research_results = "\n\n".join(research_result_list)

    else:
        raise NotImplementedError("Only '*concatenate*' is currently supported")

    # Create a prompt for the object consolidation

    if agent_5_base_data is None:
        dc_formatting_prompt = DC_FORMATTING_NO_BASE_DATA_PROMPT.format(
            text=research_results,
            format=agent_5_output_objective,
        )
    else:
        dc_formatting_prompt = DC_FORMATTING_WITH_BASE_DATA_PROMPT.format(
            base_data=agent_5_base_data,
            text=research_results,
            format=agent_5_output_objective,
        )

    # Run LLM

    msg = [
        HumanMessage(
            content=trim_prompt_piece(
                config=graph_config.tooling.primary_llm.config,
                prompt_piece=dc_formatting_prompt,
                reserved_str="",
            ),
        )
    ]

    dispatch_timings: list[float] = []

    primary_model = graph_config.tooling.primary_llm

    def stream_initial_answer() -> list[str]:
        response: list[str] = []
        for message in primary_model.stream(msg, timeout_override=30, max_tokens=None):
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
            end_stream_token = datetime.now()
            dispatch_timings.append(
                (end_stream_token - start_stream_token).microseconds
            )
            response.append(content)
        return response

    try:
        _ = run_with_timeout(
            60,
            stream_initial_answer,
        )

    except Exception as e:
        raise ValueError(f"Error in consolidate_research: {e}")

    logger.debug("DivCon Step A5 - Final Generation - completed")

    return ResearchUpdate(
        research_results=research_results,
        log_messages=["Agent Source Consilidation done"],
    )
