from typing import Literal
from typing import NotRequired

from typing_extensions import TypedDict


# Content part structures for multimodal messages
class TextContentPart(TypedDict):
    type: Literal["text"]
    text: str


class ImageUrlDetail(TypedDict):
    url: str
    detail: NotRequired[Literal["auto", "low", "high"]]


class ImageContentPart(TypedDict):
    type: Literal["image_url"]
    image_url: ImageUrlDetail


ContentPart = TextContentPart | ImageContentPart


# Tool call structures
class FunctionCall(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: Literal["function"]
    function: FunctionCall


# Message types
class SystemMessage(TypedDict):
    role: Literal["system"]
    content: str


class UserMessageWithText(TypedDict):
    role: Literal["user"]
    content: str


class UserMessageWithParts(TypedDict):
    role: Literal["user"]
    content: list[ContentPart]


UserMessage = UserMessageWithText | UserMessageWithParts


class AssistantMessage(TypedDict):
    role: Literal["assistant"]
    content: NotRequired[str | None]
    tool_calls: NotRequired[list[ToolCall]]


class ToolMessage(TypedDict):
    role: Literal["tool"]
    content: str
    tool_call_id: str


# Union type for all OpenAI Chat Completions messages
ChatCompletionMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage
