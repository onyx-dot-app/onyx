"""Operation updates shared by tool consumers and application presentation."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, JsonValue

from onyx.context.search.models import SearchDoc


class CustomToolErrorInfo(BaseModel):
    is_auth_error: bool = False
    status_code: int
    message: str


class GeneratedImage(BaseModel):
    file_id: str
    url: str
    revised_prompt: str
    shape: str | None = None


class SearchStarted(BaseModel):
    is_internet_search: bool = False


class SearchQueries(BaseModel):
    queries: list[str]


class SearchFilters(BaseModel):
    sources: list[str] = Field(default_factory=list)
    time_filter_start: datetime | None = None
    time_filter_end: datetime | None = None


class SearchDocuments(BaseModel):
    documents: list[SearchDoc]


class OpenUrlStarted(BaseModel):
    pass


class OpenUrlTargets(BaseModel):
    urls: list[str]


class UrlDocuments(BaseModel):
    documents: list[SearchDoc]


class ImageGenerationStarted(BaseModel):
    pass


class ImageGenerationHeartbeat(BaseModel):
    pass


class ImagesGenerated(BaseModel):
    images: list[GeneratedImage]


class PythonStarted(BaseModel):
    code: str


class PythonOutput(BaseModel):
    stdout: str = ""
    stderr: str = ""
    file_ids: list[str] = Field(default_factory=list)


class CustomToolStarted(BaseModel):
    tool_name: str
    tool_id: int | None = None


class CustomToolArguments(BaseModel):
    tool_name: str
    tool_args: dict[str, JsonValue]


class CustomToolOutput(BaseModel):
    tool_name: str
    tool_id: int | None = None
    response_type: str
    data: JsonValue = None
    file_ids: list[str] | None = None
    error: CustomToolErrorInfo | None = None


class FileReadStarted(BaseModel):
    pass


class FileReadResult(BaseModel):
    file_name: str
    file_id: str
    start_char: int
    end_char: int
    total_chars: int
    preview_start: str = ""
    preview_end: str = ""


class MemoryStarted(BaseModel):
    pass


class MemoryOperation(str, Enum):
    ADD = "add"
    UPDATE = "update"


class MemoryUpdated(BaseModel):
    memory_text: str
    operation: MemoryOperation
    memory_id: int | None = None
    index: int | None = None


class CodingStarted(BaseModel):
    query: str
    repo: str


class CodingCompleted(BaseModel):
    answer: str


class BashStarted(BaseModel):
    cmd: str


class BashOutput(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False


class ResearchStarted(BaseModel):
    research_task: str
