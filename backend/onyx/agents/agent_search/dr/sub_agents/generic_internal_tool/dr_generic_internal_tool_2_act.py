import json
from datetime import datetime
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.sub_agents.states import IterationAnswer
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.prompts.dr_prompts import CUSTOM_TOOL_PREP_PROMPT
from onyx.prompts.dr_prompts import CUSTOM_TOOL_USE_PROMPT
from onyx.prompts.dr_prompts import OKTA_TOOL_USE_SPECIAL_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generic_internal_tool_act(
    state: BranchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> BranchUpdate:
    """
    LangGraph node to perform a generic tool call as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    generic_internal_tool_info = state.available_tools[state.tools_used[-1]]
    generic_internal_tool_name = generic_internal_tool_info.llm_path
    generic_internal_tool = generic_internal_tool_info.tool_object

    if generic_internal_tool is None:
        raise ValueError("generic_internal_tool is not set")

    branch_query = state.branch_question
    if not branch_query:
        raise ValueError("branch_query is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query

    logger.debug(
        f"Tool call start for {generic_internal_tool_name} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # get tool call args
    tool_args: dict | None = None
    if graph_config.tooling.using_tool_calling_llm:
        # get tool call args from tool-calling LLM
        tool_use_prompt = CUSTOM_TOOL_PREP_PROMPT.build(
            query=branch_query,
            base_question=base_question,
            tool_description=generic_internal_tool_info.description,
        )
        tool_calling_msg = graph_config.tooling.primary_llm.invoke(
            tool_use_prompt,
            tools=[generic_internal_tool.tool_definition()],
            tool_choice="required",
            timeout_override=TF_DR_TIMEOUT_SHORT,
        )

        # make sure we got a tool call
        if (
            isinstance(tool_calling_msg, AIMessage)
            and len(tool_calling_msg.tool_calls) == 1
        ):
            tool_args = tool_calling_msg.tool_calls[0]["args"]
        else:
            logger.warning("Tool-calling LLM did not emit a tool call")

    if tool_args is None:
        # get tool call args from non-tool-calling LLM or for failed tool-calling LLM
        tool_args = generic_internal_tool.get_args_for_non_tool_calling_llm(
            query=branch_query,
            history=[],
            llm=graph_config.tooling.primary_llm,
            force_run=True,
        )

    if tool_args is None:
        raise ValueError("Failed to obtain tool arguments from LLM")

    # run the tool
    tool_responses = list(generic_internal_tool.run(**tool_args))
    final_data = generic_internal_tool.final_result(*tool_responses)
    tool_result_str = json.dumps(final_data, ensure_ascii=False)

    tool_str = (
        f"Tool used: {generic_internal_tool.display_name}\n"
        f"Description: {generic_internal_tool_info.description}\n"
        f"Result: {tool_result_str}"
    )

    if generic_internal_tool.display_name == "Okta Profile":
        tool_prompt = OKTA_TOOL_USE_SPECIAL_PROMPT
    else:
        tool_prompt = CUSTOM_TOOL_USE_PROMPT

    tool_summary_prompt = tool_prompt.build(
        query=branch_query, base_question=base_question, tool_response=tool_str
    )
    answer_string = str(
        graph_config.tooling.primary_llm.invoke(
            tool_summary_prompt, timeout_override=TF_DR_TIMEOUT_SHORT
        ).content
    ).strip()

    logger.debug(
        f"Tool call end for {generic_internal_tool_name} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=generic_internal_tool.llm_name,
                tool_id=generic_internal_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=branch_query,
                answer=answer_string,
                claims=[],
                cited_documents={},
                reasoning="",
                additional_data=None,
                response_type="text",  # TODO: convert all response types to enums
                data=answer_string,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="custom_tool",
                node_name="tool_calling",
                node_start_time=node_start_time,
            )
        ],
    )
