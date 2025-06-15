from typing import Any, cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.orchestration.nodes.base_tool_node import execute_tool_node
from onyx.agents.agent_search.orchestration.nodes.tool_node_utils import emit_early_tool_kickoff
from onyx.context.search.utils import dedupe_documents
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
    SearchResponseSummary,
)
from onyx.tools.tool_implementations.search.search_utils import section_to_llm_doc
from onyx.tools.tool_implementations.search_like_tool_utils import (
    FINAL_CONTEXT_DOCUMENTS_ID,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SEARCH_NODE_INSTRUCTIONS = """Use the search tool to find relevant information from the knowledge base.

You MUST use the search tool - do not respond to the user directly. After searching, the system will decide whether to search again or provide a response.

Focus on finding the most relevant information to answer the user's question."""


def search_node(
    state: Any, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict[str, Any]:
    """
    Search-specific node that:
    1. Forces use of the search tool
    2. Saves search results to database and prompt builder
    3. Loops back to action router for potential additional searches
    """
    # Emit early tool kickoff for immediate user feedback
    emit_early_tool_kickoff("run_search", writer)

    return execute_tool_node(
        state=state,
        config=config,
        writer=writer,
        tool_filter_fn=lambda tools: [tool for tool in tools if tool.name == "run_search"],
        instructions=_SEARCH_NODE_INSTRUCTIONS,
        tool_type="search",
        extract_results_fn=_extract_search_results,
    )


def _extract_search_results(tool_responses: list) -> dict:
    """Extract search results from tool responses for citation handling."""
    final_search_results = []
    initial_search_results = []

    for yield_item in tool_responses:
        if yield_item.id == FINAL_CONTEXT_DOCUMENTS_ID:
            final_search_results = yield_item.response
        elif yield_item.id == SEARCH_RESPONSE_SUMMARY_ID:
            search_response_summary = cast(SearchResponseSummary, yield_item.response)
            try:
                deduped_results = dedupe_documents(search_response_summary.top_sections)
                if deduped_results and len(deduped_results) > 0 and deduped_results[0]:
                    initial_search_results = [
                        section_to_llm_doc(section) for section in deduped_results[0]
                    ]
                else:
                    initial_search_results = []
            except (IndexError, TypeError) as e:
                logger.error(f"Error extracting search results: {e}")
                initial_search_results = []

    return {
        "final_search_results": final_search_results,
        "initial_search_results": initial_search_results,
    }
