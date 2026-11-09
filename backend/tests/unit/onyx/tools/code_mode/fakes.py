"""Fake tools for code mode tests."""

import json
import time
from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from onyx.agents.tools import ToolExecutionMode, ToolInvocation, ToolOutcome
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.server.features.mcp.models import MCPServerConnection
from onyx.tools.interface import Tool
from onyx.tools.models import CodeModeExposure, ToolContext
from onyx.tools.tool_implementations.code_mode.models import (
    SandboxLimits,
)
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool

RunFunction = Callable[[ToolInvocation, ToolContext], ToolOutcome]


class FakeTool(Tool):
    def __init__(
        self,
        name: str,
        run: RunFunction,
        *,
        parameters: dict[str, JsonValue] | None = None,
        description: str = "A fake tool.",
        execution_mode: ToolExecutionMode = ToolExecutionMode.PARALLEL,
        exposure: CodeModeExposure = CodeModeExposure.IMMEDIATE,
    ) -> None:
        self._name = name
        self._exposure = exposure
        self._run_function = run
        self._parameters: dict[str, JsonValue] = (
            parameters
            if parameters is not None
            else {
                "type": "object",
                "properties": {"value": {"type": "string", "description": "A value."}},
                "required": ["value"],
            }
        )
        self._description = description
        self._execution_mode = execution_mode

    @property
    def id(self) -> int:
        return 7

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def display_name(self) -> str:
        return self._name

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return self._execution_mode

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return self._exposure

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=self._description,
            parameters=self._parameters,
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        return self._run_function(invocation, context)


# Sandbox limits for tests that run real programs.
LIMITS = SandboxLimits(
    lifetime_seconds=10,
    max_tool_calls=20,
    max_output_chars=2_000,
    max_memory_bytes=32 * 1024 * 1024,
    max_cpu_seconds=2,
)


def search_doc(document_id: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier=f"Title {document_id}",
        link=f"https://example.com/{document_id}",
        blurb="blurb",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
        updated_at=datetime(2026, 1, 1),
    )


def search_result(document_ids: list[str], citation_start: int) -> ToolResult:
    """A result shaped like the built-in search tools' output."""
    mapping = {
        citation_start + offset: document_id
        for offset, document_id in enumerate(document_ids)
    }
    content = json.dumps(
        {
            "results": [
                {
                    "document": number,
                    "title": f"Title {document_id}",
                    "content": f"Content of {document_id}",
                }
                for number, document_id in mapping.items()
            ]
        }
    )
    return ToolResult(
        content=content,
        details=SearchDocsResponse(
            search_docs=[search_doc(document_id) for document_id in document_ids],
            citation_mapping=mapping,
        ),
    )


class FakeWebSearchTool(WebSearchTool):
    """A web search tool with a scripted run; stubs treat it as a search tool."""

    def __init__(self, run: RunFunction) -> None:
        self._id = 3
        self._run_function = run

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        outcome = self._run_function(invocation, context)
        assert isinstance(outcome, ToolResult)
        return outcome


class FakeMCPTool(MCPTool):
    """An MCP tool whose server is scripted; results use the MCP envelope."""

    def __init__(
        self,
        name: str,
        run: RunFunction,
        parameters: dict[str, JsonValue],
        *,
        server: str = "acme",
        output_schema: dict[str, JsonValue] | None = None,
    ) -> None:
        self._id = 12
        self.mcp_server = MCPServerConnection.model_construct(name=server)
        self._mcp_tool_name = name
        self._output_schema = output_schema
        self._name = name
        self._llm_name = name
        self._description = f"MCP tool {name}."
        self._display_name = name
        self._tool_definition = parameters
        self._run_function = run

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        outcome = self._run_function(invocation, context)
        assert isinstance(outcome, ToolResult)
        return outcome


def echo(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
    """A tool that returns its `value` argument as `{"echo": value}`."""
    return ToolResult(content=json.dumps({"echo": invocation.arguments["value"]}))


def search(invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
    """A search tool that finds two documents for each query."""
    queries = invocation.arguments["queries"]
    assert isinstance(queries, list)
    return search_result(
        [f"{query}-{n}" for query in queries for n in range(2)],
        context.next_citation_num,
    )


def until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    """Wait for `condition`; fails the test after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "the condition did not hold in time"
        time.sleep(0.01)
