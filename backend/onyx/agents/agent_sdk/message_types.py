"""Strongly typed message structures for Agent SDK messages."""

from typing import Literal

from typing_extensions import TypedDict


# Content types
class TextContent(TypedDict):
    type: Literal["text", "input_text"]
    text: str


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
    content: list[TextContent]


class UserMessage(TypedDict):
    role: Literal["user"]
    content: list[TextContent | ImageContent]


class AssistantMessageWithContent(TypedDict):
    role: Literal["assistant"]
    content: list[TextContent]


class AssistantMessageWithToolCalls(TypedDict):
    role: Literal["assistant"]
    tool_calls: list[ToolCall]


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


# Union type for all Agent SDK messages
AgentSDKMessage = (
    SystemMessage
    | UserMessage
    | AssistantMessageWithContent
    | AssistantMessageWithToolCalls
    | ToolMessage
    | FunctionCallMessage
    | FunctionCallOutputMessage
)
