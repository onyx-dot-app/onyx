"""Fake tools for code mode tests."""

import time
from collections.abc import Callable

from pydantic import JsonValue

from onyx.agents.tools import ToolExecutionMode, ToolInvocation, ToolOutcome
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.server.features.mcp.models import MCPServerConnection
from onyx.tools.interface import Tool
from onyx.tools.models import CodeModeExposure, ToolContext
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
        self._parameters: dict[str, JsonValue] = parameters or {
            "type": "object",
            "properties": {"value": {"type": "string", "description": "A value."}},
            "required": ["value"],
        }
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


def until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    """Wait for `condition`; fails the test after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "the condition did not hold in time"
        time.sleep(0.01)
