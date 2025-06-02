from typing import TypedDict, Optional
from pydantic import BaseModel
from langchain_core.messages import AIMessageChunk
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.agents.agent_search.shared_graph_utils.models import AgentErrorLog

class DocumentChatInput(BaseModel):
    query: str
    document_ids: list[str] = []  # Document IDs to analyze
    document_content: Optional[str] = None  # The text content to edit if provided

class DocumentChatOutput(TypedDict):
    response_chunk: AIMessageChunk
    edited_document: Optional[str]
    search_results: Optional[str]

class SearchResultUpdate(BaseModel):
    """Update containing search results."""
    search_results: Optional[str] = None
    search_performed: bool = False
    search_error: Optional[AgentErrorLog] = None

class DocumentEditUpdate(BaseModel):
    """Update containing document edit information."""
    original_text: Optional[str] = None
    edited_text: Optional[str] = None
    edit_instructions: Optional[str] = None
    edit_successful: bool = False
    edit_error: Optional[AgentErrorLog] = None

class DocumentChatState(
    DocumentChatInput,
    ToolChoiceInput,
    ToolCallUpdate, 
    ToolChoiceUpdate,
    SearchResultUpdate,
    DocumentEditUpdate,
):
    pass
