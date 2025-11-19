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
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
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

    graph_config = cast(GraphConfig, config["metadata"]["config"])

    search_tool = graph_config.tooling.search_tool

    if search_tool is None or graph_config.inputs.persona is None:
        raise ValueError("Search tool and persona must be provided for DivCon search")

    # Populate prompt
    instructions = graph_config.inputs.persona.system_prompt or ""

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

    try:
        _ = run_with_timeout(
            60,
            lambda: stream_llm_answer(
                llm=graph_config.tooling.primary_llm,
                prompt=msg,
                event_name="initial_agent_answer",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=30,
                max_tokens=None,
            ),
        )

    except Exception as e:
        raise ValueError(f"Error in consolidate_research: {e}")

    logger.debug("DivCon Step A5 - Final Generation - completed")

    return ResearchUpdate(
        research_results=research_results,
        log_messages=["Agent Source Consilidation done"],
    )
