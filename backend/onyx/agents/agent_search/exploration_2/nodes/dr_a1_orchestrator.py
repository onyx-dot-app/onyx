from datetime import datetime
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    ORCHESTRATOR_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.enums import DRPath
from onyx.agents.agent_search.exploration_2.models import IterationAnswer
from onyx.agents.agent_search.exploration_2.states import IterationInstructions
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.states import OrchestrationUpdate
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
        "description": """The INTERNAL search tool's functionality is described in the system prompt. \
Use it if you think you have one or  more questions that you believe are \
suitable for the INTERNAL search tool which can search internal documents. If provided, the 'covered' and 'not_covered' \
lists in the system prompt MAY give an indication whether the question is likely suitable for the INTERNAL search tool.
Make sure that each question has the sufficient context to be answered. \
If available, use information from the memory that may be available \
in the conversation history to provide sharper/better context to the questions you want to have done \
a search for. As an example, if \
the original question refers to 'availability products', and the memory extraction has an \
explicit list of products that enhance availability, you probably want to use the product list to construct \
the questions for the search tool. \
Or, if should a question refer to 'typical customers' and the memory extraction contains characteristics \
of typical customers, you probably want \
to use those characteristics for the question generation for the search tool.

The tool takes a list of requests, and for each request, it mandatory requires a search query, reasoning information, \
but can optionally take a source filters, a start date filter, and an end date filter.
Source filters can be 'github', 'slack', 'confluence', 'jira', 'email', 'file', 'linear', 'call'.. This field is a list \
of strings. If the list is kept empty, no filters are applied.
The date fields should be in the format 'YYYY-MM-DD'. If the date fields are kept empty, no date filters are applied.

NOTE: don't be redundant, NEVER use source or date filter information in the search query itself! If the original question \
had implied a filter, pupulate the source_filters and date_filter_start and date_filter_end fields accordingly, but \
do not insert the information into the search query itself! \
If a filter is chosen, the filter content MUST NOT be repeated in the search query itself! \
(Example: if the  source filter is ['github'], the search query MUST NOT contain 'github' in the search query itself. \
Similar for date filters!)!

""",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "array",
                    "description": "The list of questions to be asked of the internal search tool.",
                    "items": {
                        "type": "object",
                        "description": "The individual question with optional filters to be asked of the internal search tool",
                        "properties": {
                            "source_filters": {
                                "type": "array",
                                "description": "Optional filter to restrict the search to specific sources.",
                                "items": {
                                    "type": "string",
                                    "description": "Individual source to filter by",
                                },
                            },
                            "date_filter_start": {
                                "type": "string",
                                "description": "Optional start date for filtering search results.",
                            },
                            "date_filter_end": {
                                "type": "string",
                                "description": "Optional end date for filtering search results.",
                            },
                            "query": {
                                "type": "string",
                                "description": "The search query to be asked of the internal search tool, NOT containing \
source or date filter information anymore!!",
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "A brief explanation of why the query was chosen,  \
particularly if and why filters are present in the query \
when you are explicitly told not to repeat source or date filters! Please comment on filter usage in query!",
                            },
                        },
                        "required": ["question"],
                    },
                },
            },
            "required": ["request"],
        },
    },
}

_WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search_tool",
        "description": """This tool is used to search the web for information. It should be used if information \
is public and either internal searches (if available) have already been done, or the information requested \
is unlikely to be found in the internal documents.
""",
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "array",
                    "description": "The list of questions to be asked of the web search tool.",
                    "items": {
                        "type": "string",
                        "description": "The individual question to be asked of the web search tool",
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

_QUERY_INDEPENDENT_CONTEXT_EXPLORER_TOOL = {
    "type": "function",
    "function": {
        "name": "query_independent_context_explorer_tool",
        "description": """This tool can be used to acquire more context from a 'memory' that has \
information about the user, their \
company. If you think that the question implicitly relates to something the user \
expects you to know about them or their company in order to answer the question, you should use this tool to acquire the \
necessary context. Common - but not exclusive(!) - signals may be a 'I', 'we', 'our', 'us', etc. in the question. \
(In fact, if these \
signals are present, you must use this tool if available, even if you think you have all the information you need \
to answer the question.) \
Use this tool if you think it can help TO PROVIDE CONTEXT or INSTRUCTIONS FOR THE  question, but do NOT use \
this tool to find actual answer information; it is just for providing context and instructions!""",
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

_QUERY_DEPENDENT_CONTEXT_EXPLORER_TOOL = {
    "type": "function",
    "function": {
        "name": "query_dependent_context_explorer_tool",
        "description": """This tool can be used to aquire more context from a 'memory' that has \
information about how similar queries were answered in the past. If you think that the question may be somewhat complex \
and using experiences and learnings from similar queries may help to answer the question, you should use this tool.
Only use this tool though if you think LEARNINGS and INSTRUCTIONS based on previous, similar queries may be useful to \
answer the user's question/request. NEVER use this tool to find actual answer information and facts for the user's \
question/request; \
this is what the non-context and non-thinking tools are for. This tool is just for providing context and instructions \
to guide \
the answer process, not providing actual answer information and facts!""",
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

    response_wrapper = ""

    message_history_for_continuation = state.message_history_for_continuation
    new_messages_for_continuation: list[SystemMessage | HumanMessage | AIMessage] = []

    if iteration_nr > 0:
        last_iteration_responses = [
            x
            for x in state.iteration_responses
            if x.iteration_nr == iteration_nr and x.tool != DRPath.CLARIFIER.value
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
        and previous_tool_call_name != DRPath.QUERY_INDEPENDENT_CONTEXT_EXPLORER.value
        and previous_tool_call_name != DRPath.QUERY_DEPENDENT_CONTEXT_EXPLORER.value
        and previous_tool_call_name != DRPath.THINKING.value
        and DRPath.INTERNAL_SEARCH.value in state.tools_used
    ):
        tools.append(_CLOSER_TOOL)  # only hgo to closer after at least one search

    if (
        _EXPLORATION_TEST_USE_THINKING
        and previous_tool_call_name != DRPath.THINKING.value
    ):
        tools.append(_THINKING_TOOL)

    if "Web Search" in [tool.name for tool in state.available_tools.values()]:
        tools.append(_WEB_SEARCH_TOOL)

    if (
        _EXPLORATION_TEST_USE_CALRIFIER
        and previous_tool_call_name != DRPath.CLARIFIER.value
    ):
        tools.append(_CLARIFIER_TOOL)

    if (
        _EXPLORATION_TEST_USE_CONTEXT_EXPLORER
        and num_search_iterations <= 2
        and DRPath.QUERY_INDEPENDENT_CONTEXT_EXPLORER.value not in state.tools_used
    ):
        tools.append(_QUERY_INDEPENDENT_CONTEXT_EXPLORER_TOOL)

    if (
        _EXPLORATION_TEST_USE_CONTEXT_EXPLORER
        and num_search_iterations <= 2
        and DRPath.QUERY_DEPENDENT_CONTEXT_EXPLORER.value not in state.tools_used
    ):
        tools.append(_QUERY_DEPENDENT_CONTEXT_EXPLORER_TOOL)

    in_orchestration_iteration_answers: list[IterationAnswer] = []

    iteration_available_tools_for_thinking_string = ""
    for tool in tools:
        if tool["function"]["name"] != "thinking_tool":
            iteration_available_tools_for_thinking_string += (
                f"{tool['function']['name']}: {tool['function']['description']}\n\n"
            )

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
                elif tool_call["name"] == "query_independent_context_explorer_tool":
                    reasoning_result = tool_call["args"]["request"]
                    next_tool_name = DRPath.QUERY_INDEPENDENT_CONTEXT_EXPLORER.value
                elif tool_call["name"] == "query_dependent_context_explorer_tool":
                    reasoning_result = tool_call["args"]["request"]
                    next_tool_name = DRPath.QUERY_DEPENDENT_CONTEXT_EXPLORER.value
                elif tool_call["name"] == "thinking_tool":
                    reasoning_result = tool_call["args"]["request"]
                    next_tool_name = DRPath.THINKING.value
                elif tool_call["name"] == "web_search_tool":
                    query_list = tool_call["args"]["request"]
                    next_tool_name = DRPath.WEB_SEARCH.value
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
            response_wrapper = "No further tool calls were requested."

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
        iteration_responses=[],
        num_search_iterations=num_search_iterations,
        iteration_available_tools_for_thinking_string=iteration_available_tools_for_thinking_string,
        traces=[response_wrapper],
    )
