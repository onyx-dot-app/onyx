from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration_2.enums import DRPath
from onyx.agents.agent_search.exploration_2.models import IterationAnswer
from onyx.agents.agent_search.exploration_2.states import FinalUpdate
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.states import OrchestrationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.utils.logger import setup_logger


logger = setup_logger()


def thinking(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate | OrchestrationUpdate:
    """
    LangGraph node to identify suitable context from memory
    """

    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question
    graph_config.persistence.db_session

    if not base_question:
        raise ValueError("Question is required for closer")

    new_messages: list[SystemMessage | HumanMessage | AIMessage] = []

    past_messages = state.message_history_for_continuation

    iteration_available_tools_for_thinking_string = (
        state.iteration_available_tools_for_thinking_string
        or "No tools available. Just think about what you would like to do next in general."
    )

    THINKING_PROMPT_TEMPLATE = f"""
It was not clear what to do next. Please think through the message history and think about what you should do next. \
Particularly focus on which tool to pick and what you would want to get from that tool.

Here are the tools you have available and the instructions you have been given for each tool:

{iteration_available_tools_for_thinking_string }

Please answer.
"""

    message_context = past_messages + [HumanMessage(content=THINKING_PROMPT_TEMPLATE)]

    thinking_result = invoke_llm_raw(
        llm=graph_config.tooling.primary_llm,
        prompt=message_context,
        tools=[],
    )

    thinking_result = thinking_result.content

    new_messages.append(AIMessage(content=thinking_result))

    in_orchestration_iteration_answers = IterationAnswer(
        tool=DRPath.THINKING.value,
        tool_id=102,
        iteration_nr=state.iteration_nr,
        parallelization_nr=0,
        question="",
        cited_documents={},
        answer=thinking_result,
        reasoning=thinking_result,
    )

    return OrchestrationUpdate(
        message_history_for_continuation=new_messages,
        iteration_responses=[in_orchestration_iteration_answers],
    )
