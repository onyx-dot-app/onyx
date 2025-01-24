from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.basic.states import BasicOutput
from onyx.agents.agent_search.basic.states import BasicState
from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.chat.models import LlmDoc
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.tools.tool_implementations.search_like_tool_utils import (
    ORIGINAL_CONTEXT_DOCUMENTS_ID,
)


def basic_use_tool_response(state: BasicState, config: RunnableConfig) -> BasicOutput:
    agent_config = cast(AgentSearchConfig, config["metadata"]["config"])
    structured_response_format = agent_config.structured_response_format
    llm = agent_config.primary_llm
    tool_choice = state["tool_choice"]
    if tool_choice is None:
        raise ValueError("Tool choice is None")
    tool = tool_choice["tool"]
    prompt_builder = agent_config.prompt_builder
    tool_call_summary = state["tool_call_summary"]
    tool_call_responses = state["tool_call_responses"]
    state["tool_call_final_result"]
    new_prompt_builder = tool.build_next_prompt(
        prompt_builder=prompt_builder,
        tool_call_summary=tool_call_summary,
        tool_responses=tool_call_responses,
        using_tool_calling_llm=agent_config.using_tool_calling_llm,
    )

    initial_search_results = []
    for yield_item in tool_call_responses:
        if yield_item.id == FINAL_CONTEXT_DOCUMENTS_ID:
            cast(list[LlmDoc], yield_item.response)
        elif yield_item.id == ORIGINAL_CONTEXT_DOCUMENTS_ID:
            search_contexts = yield_item.response.contexts
            for doc in search_contexts:
                if doc.document_id not in initial_search_results:
                    initial_search_results.append(doc)

            initial_search_results = cast(list[LlmDoc], initial_search_results)

    stream = llm.stream(
        prompt=new_prompt_builder.build(),
        structured_response_format=structured_response_format,
    )

    # For now, we don't do multiple tool calls, so we ignore the tool_message
    process_llm_stream(stream, True)

    return BasicOutput()
