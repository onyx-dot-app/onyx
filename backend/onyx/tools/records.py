"""Display tool records and records with durable model-message identity."""

from typing import Any

from pydantic import BaseModel

from onyx.context.search.models import SearchDoc
from onyx.tools.results import GeneratedImage, PythonExecutionFile


class ToolCallInfo(BaseModel):
    # The parent_tool_call_id is the actual generated tool call id
    # It is NOT the DB ID which often does not exist yet when the ToolCallInfo is created
    # None if attached to the Chat Message directly
    parent_tool_call_id: str | None
    turn_index: int
    tab_index: int
    tool_name: str
    tool_call_id: str
    tool_id: int
    reasoning_tokens: str | None
    tool_call_arguments: dict[str, Any]
    tool_call_response: str
    search_docs: list[SearchDoc] | None = None
    generated_images: list[GeneratedImage] | None = None
    generated_files: list[PythonExecutionFile] | None = None
    # File-store ids of blobs custom tools saved during the call.
    generated_file_ids: list[str] | None = None


class RecordedToolCallInfo(ToolCallInfo):
    """Tool record whose call and parent can be identified across saved runs."""

    message_id: str
    parent_message_id: str | None = None

    @property
    def execution_key(self) -> tuple[str, str]:
        return self.message_id, self.tool_call_id

    @property
    def parent_execution_key(self) -> tuple[str, str] | None:
        if self.parent_tool_call_id is None:
            return None
        if self.parent_message_id is None:
            raise ValueError("Child tool has no parent message identity")
        return self.parent_message_id, self.parent_tool_call_id
