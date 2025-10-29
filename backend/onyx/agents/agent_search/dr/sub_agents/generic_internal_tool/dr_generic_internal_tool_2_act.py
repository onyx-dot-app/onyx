import json
from datetime import datetime
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import OrchestratorTool
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
from onyx.tools.tool_implementations.agent.agent_tool import AgentTool
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

    # Check if this is an AgentTool - handle it differently
    if isinstance(generic_internal_tool, AgentTool):
        return handle_agent_tool_delegation(
            state=state,
            config=config,
            writer=writer,
            agent_tool_info=generic_internal_tool_info,
            node_start_time=node_start_time,
        )

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


def handle_agent_tool_delegation(
    state: BranchInput,
    config: RunnableConfig,
    writer: StreamWriter,
    agent_tool_info: OrchestratorTool,
    node_start_time: datetime,
) -> BranchUpdate:
    """Handle AgentTool delegation with simplified processing.

    AgentTool runs its own agent with its own tools and LLM orchestration.
    We don't need to:
    - Extract tool arguments via LLM (AgentTool just takes a query string)
    - Summarize the result via LLM (the subagent already produces a final answer)

    The subagent will make its own tool calls, which will be tracked separately
    and marked with calling_agent_name by the Answer infrastructure.
    """
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import SystemMessage

    from onyx.db.persona import get_persona_by_id
    from onyx.llm.factory import get_llms_for_persona

    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr

    branch_query = state.branch_question
    if not branch_query:
        raise ValueError("branch_query is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    agent_tool = cast(AgentTool, agent_tool_info.tool_object)
    agent_name = agent_tool.display_name

    logger.info(
        f"AgentTool delegation start for {agent_name} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Get the target persona
    target_persona = get_persona_by_id(
        persona_id=agent_tool.target_persona_id,
        user=None,  # Bypass auth for subagent calls
        db_session=graph_config.persistence.db_session,
        include_deleted=False,
        is_for_edit=False,
    )

    # Get the LLM for the subagent persona
    llm, fast_llm = get_llms_for_persona(
        persona=target_persona,
        llm_override=None,
        additional_headers=None,
    )

    # For now, we'll run a simple LLM call for the subagent
    # rather than a full nested deep research graph.
    # This keeps the implementation simpler while still avoiding double-summarization.
    # TODO: Implement full subagent delegation with its own tool orchestration
    final_response = ""

    try:
        # Build a simple prompt for the subagent
        subagent_system_prompt = f"You are {target_persona.name}. "
        if target_persona.task_prompt:
            subagent_system_prompt += target_persona.task_prompt

        subagent_user_prompt = f"Please help with the following: {branch_query}"

        # Get a simple response from the subagent's LLM
        from langchain_core.messages import SystemMessage
        from langchain_core.messages import HumanMessage

        messages = [
            SystemMessage(content=subagent_system_prompt),
            HumanMessage(content=subagent_user_prompt),
        ]

        response = llm.invoke(messages)
        final_response = str(response.content).strip()

        if not final_response:
            final_response = f"Subagent {target_persona.name} completed the task"

    except Exception as e:
        logger.exception(f"Error executing subagent {target_persona.name}")
        final_response = f"Error executing subagent: {str(e)}"

    # Create simplified IterationAnswer for the delegation itself
    answer_string = (
        final_response.strip() if final_response else f"Delegated to {agent_name}"
    )
    reasoning_string = f"Delegated to {agent_name}: {branch_query}"

    logger.info(
        f"AgentTool delegation end for {agent_name} {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=agent_tool.llm_name,
                tool_id=agent_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=branch_query,
                answer=answer_string,
                claims=[],
                cited_documents={},
                reasoning=reasoning_string,
                additional_data={"subagent_name": target_persona.name},
                response_type="agent_delegation",
                data=final_response,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="agent_tool_delegation",
                node_name=agent_name,
                node_start_time=node_start_time,
            )
        ],
    )
