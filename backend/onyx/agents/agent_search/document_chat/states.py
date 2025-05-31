from typing import TypedDict
from pydantic import BaseModel
from langchain_core.messages import AIMessageChunk
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate

class DocumentChatInput(BaseModel):
    query: str
    document_ids: list[str] = []  # Document IDs to analyze

class DocumentChatOutput(TypedDict):
    response_chunk: AIMessageChunk

class DocumentChatState(
    DocumentChatInput,
    ToolChoiceInput,
    ToolCallUpdate, 
    ToolChoiceUpdate,
):
    pass  # SearchTool handles all document retrieval and analysis
