from datetime import datetime
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    CONTEXT_EXPLORER_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.enums import ResearchType
from onyx.agents.agent_search.exploration_2.states import FinalUpdate
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.states import OrchestrationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.utils.logger import setup_logger

logger = setup_logger()


def context_explorer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate | OrchestrationUpdate:
    """
    LangGraph node to identify suitable context from memory
    """

    datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    state.current_step_nr

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question
    if not base_question:
        raise ValueError("Question is required for closer")

    ResearchType.DEEP

    new_messages: list[SystemMessage | HumanMessage | AIMessage] = []

    user_question = state.original_question
    cs_memory = state.original_cheat_sheet_context

    context_explorer_prompt = CONTEXT_EXPLORER_PROMPT_TEMPLATE.replace(
        "---user_question---", user_question or ""
    ).replace("---current_memory---", str(cs_memory or {}))

    context_explorer_response = invoke_llm_raw(
        llm=graph_config.tooling.fast_llm, prompt=context_explorer_prompt
    )

    new_messages.append(
        HumanMessage(
            content="Below is relevant context from the MEMORY (do not use this \
information to try to answer the question directly via the CLOSER tool... it can only inform what \
questions and tasks to send to the available tools (EXCLUDING the CLOSER tool itself)):"
        )
    )
    new_messages.append(context_explorer_response)

    return OrchestrationUpdate(message_history_for_continuation=new_messages)
