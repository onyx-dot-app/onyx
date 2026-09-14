"""Executable tools with cancellation and progress callbacks."""

from collections.abc import Callable
from enum import Enum

from pydantic import ConfigDict, JsonValue

from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolDefinition, ToolResult

ToolUpdate = Callable[[ToolResult], None]


class ToolExecutionMode(str, Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class AgentTool(ToolDefinition):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    execute: Callable[
        [str, dict[str, JsonValue], CancellationSignal, ToolUpdate], ToolResult
    ]
    execution_mode: ToolExecutionMode = ToolExecutionMode.PARALLEL
