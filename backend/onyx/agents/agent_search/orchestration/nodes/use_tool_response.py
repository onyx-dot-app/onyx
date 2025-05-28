from typing import cast

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.states import BasicOutput
from onyx.agents.agent_search.basic.states import BasicState
from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import GraphConfig
from onyx.chat.models import LlmDoc
from onyx.context.search.utils import dedupe_documents
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_utils import section_to_llm_doc
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


@log_function_time(print_only=True)
def basic_use_tool_response(
    state: BasicState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> BasicOutput:
    agent_config = cast(GraphConfig, config["metadata"]["config"])
    structured_response_format = agent_config.inputs.structured_response_format
    llm = agent_config.tooling.primary_llm
    tool_choice = state.tool_choice
    if tool_choice is None:
        raise ValueError("Tool choice is None")
    tool = tool_choice.tool
    prompt_builder = agent_config.inputs.prompt_builder
    if state.tool_call_output is None:
        raise ValueError("Tool call output is None")
    tool_call_output = state.tool_call_output
    tool_call_summary = tool_call_output.tool_call_summary
    tool_call_responses = tool_call_output.tool_call_responses

    new_prompt_builder = tool.build_next_prompt(
        prompt_builder=prompt_builder,
        tool_call_summary=tool_call_summary,
        tool_responses=tool_call_responses,
        using_tool_calling_llm=agent_config.tooling.using_tool_calling_llm,
    )

    final_search_results = []
    initial_search_results = []
    for yield_item in tool_call_responses:
        if yield_item.id == FINAL_CONTEXT_DOCUMENTS_ID:
            final_search_results = cast(list[LlmDoc], yield_item.response)
        elif yield_item.id == SEARCH_RESPONSE_SUMMARY_ID:
            search_response_summary = cast(SearchResponseSummary, yield_item.response)
            # use same function from _handle_search_tool_response_summary
            initial_search_results = [
                section_to_llm_doc(section)
                for section in dedupe_documents(search_response_summary.top_sections)[0]
            ]

    new_tool_call_chunk = AIMessageChunk(content="")
    if not agent_config.behavior.skip_gen_ai_answer_generation:
        stream = llm.stream(
            prompt=new_prompt_builder.build(),
            structured_response_format=structured_response_format,
        )

        # For now, we don't do multiple tool calls, so we ignore the tool_message
        new_tool_call_chunk = process_llm_stream(
            stream,
            True,
            writer,
            final_search_results=final_search_results,
            # when the search tool is called with specific doc ids, initial search
            # results are not output. But, we still want i.e. citations to be processed.
            displayed_search_results=initial_search_results or final_search_results,
        )

    return BasicOutput(tool_call_chunk=new_tool_call_chunk)
