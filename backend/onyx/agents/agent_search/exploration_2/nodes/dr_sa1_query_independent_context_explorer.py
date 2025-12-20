import copy
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration_2.states import FinalUpdate
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.states import OrchestrationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.utils.logger import setup_logger


logger = setup_logger()


def query_independent_context_explorer(
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

    relevant_cheat_sheet_context = copy.deepcopy(state.original_cheat_sheet_context)

    del relevant_cheat_sheet_context["answer_preferences"]

    cheat_sheet_string = f"""\n\nHere is additional context learned that may inform the \
process (plan generation if applicable, reasoning, tool calls, etc.):\n{str(relevant_cheat_sheet_context)}\n###\n\n"""

    new_messages.append(HumanMessage(content=cheat_sheet_string))

    return OrchestrationUpdate(message_history_for_continuation=new_messages)
