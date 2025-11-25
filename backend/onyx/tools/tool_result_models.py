"""Base models for tool results with citation support."""

from typing import Any
from typing import Literal

from pydantic import BaseModel


class BaseCiteableToolResult(BaseModel):
    """Base class for tool results that can be cited."""

    document_citation_number: int
    unique_identifier_to_strip_away: str | None = None
    type: str


class LlmInternalSearchResult(BaseCiteableToolResult):
    """Result from an internal search query"""

    type: Literal["internal_search"] = "internal_search"
    title: str
    excerpt: str
    metadata: dict[str, Any]


class LlmWebSearchResult(BaseCiteableToolResult):
    """Result from a web search query"""

    type: Literal["web_search"] = "web_search"
    url: str
    title: str
    snippet: str


class LlmOpenUrlResult(BaseCiteableToolResult):
    """Result from opening/fetching a URL"""

    type: Literal["open_url"] = "open_url"
    content: str


class PythonExecutionFile(BaseModel):
    """File generated during Python execution"""

    filename: str
    file_link: str


class LlmPythonExecutionResult(BaseModel):
    """Result from Python code execution"""

    type: Literal["python_execution"] = "python_execution"

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    generated_files: list[PythonExecutionFile]
    error: str | None = None
