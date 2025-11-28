from typing import Any

from onyx.context.search.models import SearchDoc
from onyx.tools.models import ToolCallInfo


class LLMLoopStateContainer:
    """Container for accumulating state during LLM loop execution.

    This container holds the partial state that can be saved to the database
    if the generation is stopped by the user or completes normally.
    """

    def __init__(self):
        self.tool_calls: list[ToolCallInfo] = []
        self.reasoning_tokens: str | None = None
        self.answer_tokens: str | None = None
        # Store citation mapping for building citation_docs_info during partial saves
        self.citation_to_doc: dict[int, SearchDoc] = {}

    def add_tool_call(self, tool_call: ToolCallInfo) -> None:
        """Add a tool call to the accumulated state."""
        self.tool_calls.append(tool_call)

    def set_reasoning_tokens(self, reasoning: str | None) -> None:
        """Set the reasoning tokens from the final answer generation."""
        self.reasoning_tokens = reasoning

    def set_answer_tokens(self, answer: str | None) -> None:
        """Set the answer tokens from the final answer generation."""
        self.answer_tokens = answer

    def set_citation_mapping(self, citation_to_doc: dict[int, Any]) -> None:
        """Set the citation mapping from citation processor."""
        self.citation_to_doc = citation_to_doc
