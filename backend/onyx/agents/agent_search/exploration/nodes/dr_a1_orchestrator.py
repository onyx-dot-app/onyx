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
        "description": """The search tool's functionality is described in the system prompt. \
Use it if you think you have one or  more questions that you believe are \
suitable for the search tool.  Make sure that the question has the sufficient context to be answered. \
If available, use information from the memory that may be available \
in the conversation history to provide sharper/better context to the questions you want to have done \
a search for. As an example, if \
the original question refers to 'availability products', and the memory extraction has an \
explicit list of products that enhance availability, you probably want to include the product list in the \
question to the search tool. \
Or, if should a question refer to 'typical customers' and the memory extraction contains characteristics \
of typical customers, you probably want \
to include those characteristics in the question to the search tool. """,
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "array",
                    "description": "The list of questions to be asked of the search tool.",
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
        "description": "This tool is used if you think you need to think through the original question and the \
questions and answers you have received so far in order to make a decision about what to do next. \
Note that a final answer MUST NOT be based on memory information, so you MUST NOT suggest the Closer tool \
if the answer to the question is available only from the memory information in the conversation history! \
If in doubt, use this tool.",
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
                    "description": "A brief",
                },
            },
        },
    },
}

_CONTEXT_EXPLORER_TOOL = {
    "type": "function",
    "function": {
        "name": "context_explorer_tool",
        "description": """This tool can be used to aquire more context from a 'memory' that has \
information about the user, their \
company, and search- and reasoning strategies. If you think that the question implicitly relates to something the user \
expects you to know to answer the question, you should use this tool to aquire more context. Also, if you believe that \
answering the question may require non-trivial search- or reasoning strategies, you should use this tool to see whether \
relevant lessons have been learned in the past.
Only use this tool though if you think it can REALLY help TO PROVIDE CONTEXT or INSTRUCTIONS FOR THE user question! Do \
NOT USE IT to find information, that is what the Search Tool is for.""",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "A brief summary of what you want to learn from the memory.",
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
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The questions you would like to provide to the clarification tool, so that \
the user can be contacted.",
                },
            },
            "required": ["request"],
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
    state.use_dc
    _EXPLORATION_TEST_USE_THINKING = state.use_thinking
    _EXPLORATION_TEST_USE_CONTEXT_EXPLORER = state.use_context_explorer

    previous_tool_call_name = state.tools_used[-1] if state.tools_used else ""

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.original_question
    if not question:
        raise ValueError("Question is required for orchestrator")

    iteration_nr = state.iteration_nr
    num_search_iterations = state.num_search_iterations

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

    tools = [
        _SEARCH_TOOL,
    ]

    if (
        num_search_iterations > 0
        and previous_tool_call_name != DRPath.CONTEXT_EXPLORER.value
        and DRPath.INTERNAL_SEARCH.value in state.tools_used
    ):
        tools.append(_CLOSER_TOOL)  # only hgo to closer after at least one search

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

    if (
        _EXPLORATION_TEST_USE_CONTEXT_EXPLORER
        and num_search_iterations <= 2
        and DRPath.CONTEXT_EXPLORER.value not in state.tools_used
    ):
        tools.append(_CONTEXT_EXPLORER_TOOL)

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
                    num_search_iterations += 1
                elif tool_call["name"] == "context_explorer_tool":
                    reasoning_result = tool_call["args"]["request"]
                    next_tool_name = DRPath.CONTEXT_EXPLORER.value
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
                    message_history_for_continuation.append(
                        AIMessage(content=reasoning_result)
                    )
                    new_messages_for_continuation.append(
                        AIMessage(content=reasoning_result)
                    )

                    in_orchestration_iteration_answers.append(
                        IterationAnswer(
                            tool=DRPath.CLARIFIER.value,
                            tool_id=103,
                            iteration_nr=iteration_nr,
                            parallelization_nr=0,
                            question="",
                            cited_documents={},
                            answer=reasoning_result,
                            reasoning=reasoning_result,
                        )
                    )
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
        remaining_time_budget=remaining_time_budget - 0.5,
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
        num_search_iterations=num_search_iterations,
    )
