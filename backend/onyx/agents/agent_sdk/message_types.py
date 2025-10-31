"""Strongly typed message structures for Agent SDK messages."""

from typing import Literal

from typing_extensions import TypedDict


class InputTextContent(TypedDict):
    type: Literal["input_text"]
    text: str


class OutputTextContent(TypedDict):
    type: Literal["output_text"]
    text: str


TextContent = InputTextContent | OutputTextContent


class ImageContent(TypedDict):
    type: Literal["input_image"]
    image_url: str
    detail: str


# Tool call structures
class ToolCallFunction(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: Literal["function"]
    function: ToolCallFunction


# Message types
class SystemMessage(TypedDict):
    role: Literal["system"]
    content: list[InputTextContent]  # System messages use input text


class UserMessage(TypedDict):
    role: Literal["user"]
    content: list[
        InputTextContent | ImageContent
    ]  # User messages use input text or images


class AssistantMessageWithContent(TypedDict):
    role: Literal["assistant"]
    content: list[
        InputTextContent | OutputTextContent
    ]  # Assistant messages can receive output_text from agents SDK, but we convert to input_text


class AssistantMessageWithToolCalls(TypedDict):
    role: Literal["assistant"]
    tool_calls: list[ToolCall]


class AssistantMessageDuringAgentRun(TypedDict):
    role: Literal["assistant"]
    id: str
    content: (
        list[InputTextContent | OutputTextContent] | list[ToolCall]
    )  # Assistant runtime messages can receive output_text from agents SDK, but we convert to input_text
    status: Literal["completed", "failed", "in_progress"]
    type: Literal["message"]


class ToolMessage(TypedDict):
    role: Literal["tool"]
    content: str
    tool_call_id: str


class FunctionCallMessage(TypedDict):
    """Agent SDK function call message format."""

    type: Literal["function_call"]
    id: str
    call_id: str
    name: str
    arguments: str


class FunctionCallOutputMessage(TypedDict):
    """Agent SDK function call output message format."""

    type: Literal["function_call_output"]
    call_id: str
    output: str


class SummaryText(TypedDict):
    """Summary text item in reasoning messages."""

    text: str
    type: Literal["summary_text"]


class ReasoningMessage(TypedDict):
    """Agent SDK reasoning message format."""

    id: str
    type: Literal["reasoning"]
    summary: list[SummaryText]


# Union type for all Agent SDK messages
AgentSDKMessage = (
    SystemMessage
    | UserMessage
    | AssistantMessageWithContent
    | AssistantMessageWithToolCalls
    | AssistantMessageDuringAgentRun
    | ToolMessage
    | FunctionCallMessage
    | FunctionCallOutputMessage
    | ReasoningMessage
)
