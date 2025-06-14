from typing import Any

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.orchestration.nodes.base_tool_node import execute_tool_node

_EDIT_NODE_INSTRUCTIONS = """Use the document editor tool to make the requested changes to documents.

You MUST use the document editor tool - do not respond to the user directly. After editing, the system will provide a response to the user.

Focus on making the specific changes or edits requested by the user."""


def edit_node(
    state: Any, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict[str, Any]:
    """
    Edit-specific node that:
    1. Forces use of the document editor tool
    2. Saves edit results to database and prompt builder
    3. Goes to respond node for final response generation
    """
    return execute_tool_node(
        state=state,
        config=config,
        writer=writer,
        tool_filter_fn=lambda tools: [tool for tool in tools if tool.name == "document_editor"],
        instructions=_EDIT_NODE_INSTRUCTIONS,
        tool_type="edit",
    )
