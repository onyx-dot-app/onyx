from datetime import datetime
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration.dr_experimentation_prompts import (
    ORCHESTRATOR_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration.enums import DRPath
from onyx.agents.agent_search.exploration.enums import ResearchType
from onyx.agents.agent_search.exploration.models import IterationAnswer
from onyx.agents.agent_search.exploration.states import IterationInstructions
from onyx.agents.agent_search.exploration.states import MainState
from onyx.agents.agent_search.exploration.states import OrchestrationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.agent_configs import TF_DR_TIMEOUT_LONG
from onyx.utils.logger import setup_logger

logger = setup_logger()


_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_tool",
        "description": "This tool is the search tool whose functionality and details are  \
described in he system prompt. Use it if you think you have one or  more questions that you believe are \
suitable for the search tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "array",
                    "description": "The list of questions to be asked of the search tool",
                    "items": {
                        "type": "string",
                        "description": "The question to be asked of the search tool",
                    },
                },
            },
            "required": ["request"],
        },
    },
}

_THINKING_TOOL = {
    "type": "function",
    "function": {
        "name": "thinking_tool",
        "description": "This tool is used if yoi think you need to think through the original question and the \
questions and answers you have received so far in order to male a decision about what to do next. If in doubt, use this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "Please generate the thinking here you want to do that leads you to the next decision. This \
should end with a recommendation of which tool to invoke next.",
                },
            },
        },
    },
}

_CLOSER_TOOL = {
    "type": "function",
    "function": {
        "name": "closer_tool",
        "description": "This tool is used to close the conversation. Use it if you think you have \
all of the information you need to answer the question, and you also do not want to request additional \
information or make checks.",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The request to be made to the thinking tool",
                },
            },
        },
    },
}

_CLARIFIER_TOOL = {
    "type": "function",
    "function": {
        "name": "clarifier_tool",
        "description": "This tool is used if you need to have clarification on something IMPORTANT from \
the user. This can pertain to the original question or something you found out during the process so far.",
    },
    "parameters": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "The question you would like to ask the user to get clarification.",
            },
        },
    },
}

_DECISION_SYSTEM_PROMPT_PREFIX = "Here are general instructions by the user, which \
may or may not influence the decision what to do next:\n\n"


def _get_implied_next_tool_based_on_tool_call_history(
    tools_used: list[str],
) -> str | None:
    """
    Identify the next tool based on the tool call history. Initially, we only support
    special handling of the image generation tool.
    """
    if tools_used[-1] == DRPath.IMAGE_GENERATION.value:
        return DRPath.LOGGER.value
    else:
        return None


def orchestrator(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationUpdate:
    """
    LangGraph node to decide the next step in the DR process.
    """

    node_start_time = datetime.now()

    _EXPLORATION_TEST_USE_CALRIFIER = state.use_clarifier
    state.use_plan
    state.use_plan_updates
    state.use_corpus_history
    _EXPLORATION_TEST_USE_THINKING = state.use_thinking

    previous_tool_call_name = state.tools_used[-1] if state.tools_used else ""

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.original_question
    if not question:
        raise ValueError("Question is required for orchestrator")

    iteration_nr = state.iteration_nr

    plan_of_record = state.plan_of_record

    message_history_for_continuation = state.message_history_for_continuation
    new_messages_for_continuation: list[SystemMessage | HumanMessage | AIMessage] = []

    if iteration_nr > 0:
        last_iteration_responses = [
            x
            for x in state.iteration_responses
            if x.iteration_nr == iteration_nr
            and x.tool != DRPath.CLARIFIER.value
            and x.tool != DRPath.THINKING.value
        ]
        if last_iteration_responses:
            response_wrapper = f"For the previous iteration {iteration_nr}, here are the tool calls I decided to execute, \
    the questions and tasks posed, and responses:\n\n"
            for last_iteration_response in last_iteration_responses:
                response_wrapper += f"{last_iteration_response.tool}: {last_iteration_response.question}\n"
                response_wrapper += f"Response: {last_iteration_response.answer}\n\n"

            message_history_for_continuation.append(AIMessage(content=response_wrapper))
            new_messages_for_continuation.append(AIMessage(content=response_wrapper))

    iteration_nr += 1
    current_step_nr = state.current_step_nr

    ResearchType.DEEP
    remaining_time_budget = state.remaining_time_budget
    state.chat_history_string or "(No chat history yet available)"

    next_tool_name = None

    # Identify early exit condition based on tool call history

    next_tool_based_on_tool_call_history = (
        _get_implied_next_tool_based_on_tool_call_history(state.tools_used)
    )

    if next_tool_based_on_tool_call_history == DRPath.LOGGER.value:
        return OrchestrationUpdate(
            tools_used=[DRPath.LOGGER.value],
            query_list=[],
            iteration_nr=iteration_nr,
            current_step_nr=current_step_nr,
            log_messages=[
                get_langgraph_node_log_string(
                    graph_component="main",
                    node_name="orchestrator",
                    node_start_time=node_start_time,
                )
            ],
            plan_of_record=plan_of_record,
            remaining_time_budget=remaining_time_budget,
            iteration_instructions=[
                IterationInstructions(
                    iteration_nr=iteration_nr,
                    plan=plan_of_record.plan if plan_of_record else None,
                    reasoning="",
                    purpose="",
                )
            ],
        )

    # no early exit forced. Continue.

    state.available_tools or {}

    state.uploaded_test_context or ""
    state.uploaded_image_context or []

    # default to closer
    query_list = ["Answer the question with the information you have."]

    reasoning_result = "(No reasoning result provided yet.)"

    ORCHESTRATOR_PROMPT = ORCHESTRATOR_PROMPT_TEMPLATE

    message_history_for_continuation.append(HumanMessage(content=ORCHESTRATOR_PROMPT))
    new_messages_for_continuation.append(HumanMessage(content=ORCHESTRATOR_PROMPT))

    tools = [_SEARCH_TOOL, _CLOSER_TOOL]

    if (
        _EXPLORATION_TEST_USE_THINKING
        and previous_tool_call_name != DRPath.THINKING.value
    ):
        tools.append(_THINKING_TOOL)

    if (
        _EXPLORATION_TEST_USE_CALRIFIER
        and previous_tool_call_name != DRPath.CLARIFIER.value
    ):
        tools.append(_CLARIFIER_TOOL)

    in_orchestration_iteration_answers: list[IterationAnswer] = []
    if remaining_time_budget > 0:

        orchestrator_action: AIMessage = invoke_llm_raw(
            llm=graph_config.tooling.primary_llm,
            prompt=message_history_for_continuation,
            tools=tools,
            timeout_override=TF_DR_TIMEOUT_LONG,
            # max_tokens=1500,
        )

        tool_calls = orchestrator_action.tool_calls
        if tool_calls:
            for tool_call in tool_calls:
                if tool_call["name"] == "search_tool":
                    query_list = tool_call["args"]["request"]
                    next_tool_name = DRPath.INTERNAL_SEARCH.value
                elif tool_call["name"] == "thinking_tool":
                    reasoning_result = tool_call["args"]["request"]
                    next_tool_name = (
                        DRPath.THINKING.value
                    )  # note: thinking already done. Will return to Orchestrator.
                    message_history_for_continuation.append(
                        AIMessage(content=reasoning_result)
                    )
                    new_messages_for_continuation.append(
                        AIMessage(content=reasoning_result)
                    )

                    in_orchestration_iteration_answers.append(
                        IterationAnswer(
                            tool=DRPath.THINKING.value,
                            tool_id=102,
                            iteration_nr=iteration_nr,
                            parallelization_nr=0,
                            question="",
                            cited_documents={},
                            answer=reasoning_result,
                            reasoning=reasoning_result,
                        )
                    )

                elif tool_call["name"] == "closer_tool":
                    reasoning_result = "Time to wrap up."
                    next_tool_name = DRPath.CLOSER.value
                elif tool_call["name"] == "clarifier_tool":
                    reasoning_result = tool_call["args"]["request"]
                    next_tool_name = DRPath.CLARIFIER.value
                else:
                    raise ValueError(f"Unknown tool: {tool_call['name']}")

    else:
        reasoning_result = "Time to wrap up. All information is available"
        new_messages_for_continuation.append(AIMessage(content=reasoning_result))
        next_tool_name = DRPath.CLOSER.value

    return OrchestrationUpdate(
        tools_used=[next_tool_name or ""],
        query_list=query_list or [],
        iteration_nr=iteration_nr,
        current_step_nr=current_step_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="orchestrator",
                node_start_time=node_start_time,
            )
        ],
        plan_of_record=plan_of_record,
        remaining_time_budget=remaining_time_budget - 1.0,
        iteration_instructions=[
            IterationInstructions(
                iteration_nr=iteration_nr,
                plan=plan_of_record.plan if plan_of_record else None,
                reasoning=reasoning_result,
                purpose="",
            )
        ],
        message_history_for_continuation=new_messages_for_continuation,
        iteration_responses=in_orchestration_iteration_answers,
    )
