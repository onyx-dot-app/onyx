from typing import Any

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.orchestration.nodes.base_tool_node import (
    execute_tool_node,
)
from onyx.agents.agent_search.orchestration.nodes.tool_node_utils import (
    emit_early_tool_kickoff,
)

_REVIEW_NODE_INSTRUCTIONS = """Use the document review tool to conduct a comprehensive FDA regulatory review of documents.

You MUST use the document review tool - do not respond to the user directly. After reviewing, the system will provide a response to the user.

Focus on:
- Identifying regulatory compliance issues
- Categorizing findings by severity (critical, major, minor, observation)
- Providing specific regulatory references (CFR sections, FDA guidance)
- Offering actionable recommendations for addressing deficiencies
- Estimating review timelines and next steps

Conduct the review as an experienced FDA regulator would, following current FDA guidelines and regulatory standards."""


def review_node(
    state: Any, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> dict[str, Any]:
    """
    Review-specific node that:
    1. Forces use of the document review tool
    2. Saves review results to database and prompt builder
    3. Goes to respond node for final response generation
    """
    emit_early_tool_kickoff("document_review", writer)

    return execute_tool_node(
        state=state,
        config=config,
        writer=writer,
        tool_filter_fn=lambda tools: [
            tool for tool in tools if tool.name == "document_review"
        ],
        instructions=_REVIEW_NODE_INSTRUCTIONS,
        tool_type="review",
    )
