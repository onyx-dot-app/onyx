from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dc_search_analysis.ops import extract_section
from onyx.agents.agent_search.dc_search_analysis.states import ObjectInformationInput
from onyx.agents.agent_search.dc_search_analysis.states import ObjectResearchUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.prompts.agents.dc_prompts import DC_OBJECT_CONSOLIDATION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def consolidate_object_research(
    state: ObjectInformationInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> ObjectResearchUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    search_tool = graph_config.tooling.search_tool
    question = graph_config.inputs.prompt_builder.raw_user_query

    if search_tool is None or graph_config.inputs.persona is None:
        raise ValueError("Search tool and persona must be provided for DivCon search")

    instructions = graph_config.inputs.persona.system_prompt or ""

    agent_4_instructions = extract_section(
        instructions, "Agent Step 4:", "Agent Step 5:"
    )
    if agent_4_instructions is None:
        raise ValueError("Agent 4 instructions not found")
    agent_4_output_objective = extract_section(
        agent_4_instructions, "Output Objective:"
    )
    if agent_4_output_objective is None:
        raise ValueError("Agent 4 output objective not found")

    object_information = state.object_information

    object = object_information["object"]
    information = object_information["information"]

    # Create a prompt for the object consolidation

    dc_object_consolidation_prompt = DC_OBJECT_CONSOLIDATION_PROMPT.format(
        question=question,
        object=object,
        information=information,
        format=agent_4_output_objective,
    )

    # Run LLM

    msg = [
        HumanMessage(
            content=trim_prompt_piece(
                config=graph_config.tooling.primary_llm.config,
                prompt_piece=dc_object_consolidation_prompt,
                reserved_str="",
            ),
        )
    ]
    primary_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            30,
            primary_llm.invoke,
            prompt=msg,
            timeout_override=30,
            max_tokens=300,
        )

        cleaned_response = str(llm_response.content).replace("```json\n", "")
        consolidated_information = cleaned_response.split("INFORMATION:")[1]

    except Exception as e:
        raise ValueError(f"Error in consolidate_object_research: {e}")

    object_research_results = {
        "object": object,
        "research_result": consolidated_information,
    }

    logger.debug(
        "DivCon Step A4 - Object Research Consolidation - completed for an object"
    )

    return ObjectResearchUpdate(
        object_research_results=[object_research_results],
        log_messages=["Agent Source Consilidation done"],
    )
