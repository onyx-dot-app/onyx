"""Typed tool outputs shared by execution, storage, and presentation."""

from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, Field, JsonValue, model_validator

from onyx.context.search.models import SearchDoc


class CustomToolErrorInfo(BaseModel):
    is_unreachable: bool = False
    is_auth_error: bool = False
    status_code: int | None
    message: str


class GeneratedImage(BaseModel):
    file_id: str
    url: str
    revised_prompt: str
    shape: str | None = None


class FileReadResult(BaseModel):
    type: Literal["file_read_result"] = "file_read_result"
    file_name: str
    file_id: str
    start_char: int
    end_char: int
    total_chars: int
    preview_start: str = ""
    preview_end: str = ""


class MemoryOperation(str, Enum):
    ADD = "add"
    UPDATE = "update"


class MemoryUpdated(BaseModel):
    type: Literal["memory_result"] = "memory_result"
    memory_text: str
    operation: MemoryOperation
    memory_id: int | None = None
    index: int | None = None


class ToolExecutionError(BaseModel):
    """A tool failure that must also be shown to the user."""

    type: Literal["tool_execution_error"] = "tool_execution_error"
    message: str


class CustomToolUserFileSnapshot(BaseModel):
    file_ids: list[str]  # References to saved images or CSVs


class CustomToolCallSummary(BaseModel):
    type: Literal["custom_tool_result"] = "custom_tool_result"
    tool_name: str
    response_type: str  # e.g., 'json', 'image', 'csv', 'graph'
    # JSON field names alone cannot distinguish output from file references.
    tool_result: JsonValue | CustomToolUserFileSnapshot = Field(
        union_mode="left_to_right"
    )
    error: CustomToolErrorInfo | None = None

    @model_validator(mode="after")
    def restore_file_references(self) -> Self:
        if self.response_type in {"image", "csv"}:
            self.tool_result = CustomToolUserFileSnapshot.model_validate(
                self.tool_result
            )
        return self


class PythonExecutionFile(BaseModel):
    """File generated during Python execution"""

    filename: str
    file_link: str


class PythonExecutionDelta(BaseModel):
    """New process output from Python execution."""

    stdout: str = ""
    stderr: str = ""


class LlmPythonExecutionResult(BaseModel):
    """Result from Python code execution"""

    type: Literal["python_execution"] = "python_execution"

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    generated_files: list[PythonExecutionFile]
    error: str | None = None
    # Set when some session files are absent
    staging_notice: str | None = None


class LlmBashExecutionResult(BaseModel):
    type: Literal["bash_execution"] = "bash_execution"
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    error: str | None = None


class ResearchAgentCallResult(BaseModel):
    type: Literal["research_result"] = "research_result"
    intermediate_report: str
    citation_mapping: dict[int, SearchDoc]


class CodingAgentCallResult(BaseModel):
    type: Literal["coding_result"] = "coding_result"
    answer: str
