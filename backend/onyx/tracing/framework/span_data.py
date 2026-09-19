import abc
from collections.abc import Mapping, Sequence
from typing import Any


class SpanData(abc.ABC):
    """
    Represents span data in the trace.
    """

    @abc.abstractmethod
    def export(self) -> dict[str, Any]:
        """Export the span data as a dictionary."""

    @property
    @abc.abstractmethod
    def type(self) -> str:
        """Return the type of the span."""


class AgentSpanData(SpanData):
    """
    Represents an Agent Span in the trace.
    Includes name, handoffs, tools, and output type.
    """

    __slots__ = ("name", "handoffs", "tools", "output_type")

    def __init__(
        self,
        name: str,
        handoffs: list[str] | None = None,
        tools: list[str] | None = None,
        output_type: str | None = None,
    ):
        self.name = name
        self.handoffs: list[str] | None = handoffs
        self.tools: list[str] | None = tools
        self.output_type: str | None = output_type

    @property
    def type(self) -> str:
        return "agent"

    def export(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "handoffs": self.handoffs,
            "tools": self.tools,
            "output_type": self.output_type,
        }


class FunctionSpanData(SpanData):
    """
    Represents a Function Span in the trace.
    Includes input, output and MCP data (if applicable).
    """

    __slots__ = ("name", "input", "output", "mcp_data")

    def __init__(
        self,
        name: str,
        input: str | None,
        output: Any | None,
        mcp_data: dict[str, Any] | None = None,
    ):
        self.name = name
        self.input = input
        self.output = output
        self.mcp_data = mcp_data

    @property
    def type(self) -> str:
        return "function"

    def export(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "input": self.input,
            "output": str(self.output) if self.output else None,
            "mcp_data": self.mcp_data,
        }


class GenerationSpanData(SpanData):
    """
    Represents a Generation Span in the trace.
    Includes input, output, model, model configuration, and usage.
    """

    __slots__ = (
        "_capture_content",
        "_input",
        "_output",
        "_reasoning",
        "_tools",
        "_request_params",
        "model",
        "model_config",
        "image_count",
        "usage",
        "time_to_first_action_seconds",
    )

    def __init__(
        self,
        input: Sequence[Mapping[str, Any]] | None = None,
        output: Sequence[Mapping[str, Any]] | None = None,
        reasoning: str | None = None,
        model: str | None = None,
        model_config: Mapping[str, Any] | None = None,
        image_count: int | None = None,
        usage: dict[str, Any] | None = None,
        time_to_first_action_seconds: float | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        request_params: Mapping[str, Any] | None = None,
    ):
        if image_count is not None and image_count < 1:
            raise ValueError("image_count must be positive")
        self._capture_content = True
        self.input = input
        self.output = output
        self.reasoning = reasoning
        self.model = model
        self.model_config = model_config
        self.image_count = image_count
        self.usage = usage
        self.time_to_first_action_seconds = time_to_first_action_seconds
        self.tools = tools
        self.request_params = request_params

    @property
    def type(self) -> str:
        return "generation"

    def export(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "input": self.input,
            "output": self.output,
            "reasoning": self.reasoning,
            "model": self.model,
            "model_config": self.model_config,
            "image_count": self.image_count,
            "usage": self.usage,
            "time_to_first_action_seconds": self.time_to_first_action_seconds,
            "tools": self.tools,
            "request_params": self.request_params,
        }

    @property
    def input(self) -> Sequence[Mapping[str, Any]] | None:
        return self._input

    @input.setter
    def input(self, value: Sequence[Mapping[str, Any]] | None) -> None:
        self._input = value if self._capture_content else None

    @property
    def output(self) -> Sequence[Mapping[str, Any]] | None:
        return self._output

    @output.setter
    def output(self, value: Sequence[Mapping[str, Any]] | None) -> None:
        self._output = value if self._capture_content else None

    @property
    def reasoning(self) -> str | None:
        return self._reasoning

    @reasoning.setter
    def reasoning(self, value: str | None) -> None:
        self._reasoning = value if self._capture_content else None

    @property
    def tools(self) -> Sequence[Mapping[str, Any]] | None:
        return self._tools

    @tools.setter
    def tools(self, value: Sequence[Mapping[str, Any]] | None) -> None:
        self._tools = value if self._capture_content else None

    @property
    def request_params(self) -> Mapping[str, Any] | None:
        return self._request_params

    @request_params.setter
    def request_params(self, value: Mapping[str, Any] | None) -> None:
        self._request_params = value if self._capture_content else None

    def disable_content_capture(self) -> None:
        """Retain generation metadata but reject all operation content."""
        self._capture_content = False
        self._input = None
        self._output = None
        self._reasoning = None
        self._tools = None
        self._request_params = None
