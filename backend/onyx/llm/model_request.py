"""Provider request messages and serialization from application messages."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, JsonValue

from onyx.llm import models as app
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_capabilities import model_needs_formatting_reenabled
from onyx.llm.models import AnyThinkingBlock, ContentPart, MessageRole
from onyx.tools.tool_name import sanitize_tool_name

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLMConfig

# OpenAI reasoning models need this prefix to enable Markdown formatting.
CODE_BLOCK_MARKDOWN = "Formatting re-enabled. "


class RequestFunctionCall(BaseModel):
    """Complete function call sent in conversation history."""

    name: str
    arguments: str


class ToolCall(BaseModel):
    type: Literal["function"] = "function"
    id: str
    function: RequestFunctionCall


class CacheableMessage(BaseModel):
    # Some providers support prompt caching controls at the message level (passed through via LiteLLM).
    cache_control: dict[str, JsonValue] | None = None


class SystemMessage(CacheableMessage):
    role: Literal[MessageRole.SYSTEM] = MessageRole.SYSTEM
    content: str


class UserMessage(CacheableMessage):
    role: Literal[MessageRole.USER] = MessageRole.USER
    content: str | list[ContentPart]


class AssistantMessage(CacheableMessage):
    role: Literal[MessageRole.ASSISTANT] = MessageRole.ASSISTANT
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    thinking_blocks: list[AnyThinkingBlock] | None = None


class ToolMessage(CacheableMessage):
    role: Literal[MessageRole.TOOL] = MessageRole.TOOL
    content: str
    tool_call_id: str


ChatCompletionMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def serialize_request(
    request: app.GenerationRequest, config: LLMConfig
) -> tuple[list[ChatCompletionMessage], int]:
    """Serialize provider messages and return the cacheable prefix length."""
    history = (
        [app.SystemMessage(content=request.system_prompt, cacheable=True)]
        if request.system_prompt
        else []
    ) + request.messages
    messages: list[ChatCompletionMessage] = []
    # The last message for which cacheable is true
    # AND is true for all previous messages
    # (counting from the start of the history)
    # represents the end of the cacheable prefix
    # used for prompt caching
    cacheable_prefix = 0
    ollama = config.model_provider == LlmProviderNames.OLLAMA_CHAT
    for index, message in enumerate(history):
        if message.cacheable and cacheable_prefix == index:
            cacheable_prefix += 1
        if isinstance(message, app.AssistantMessage):
            content = [
                block.model_copy(update={"name": sanitize_tool_name(block.name)})
                if isinstance(block, app.ToolCall)
                else block
                for block in message.content
            ]
            message = message.model_copy(update={"content": content})
            if ollama and message.tool_calls:
                calls = [
                    f"[Tool Call] name={call.name} id={call.id} args={json.dumps(call.arguments)}"
                    for call in message.tool_calls
                ]
                messages.append(
                    AssistantMessage(
                        content="\n".join(
                            ([message.text] if message.text else []) + calls
                        )
                    )
                )
                continue
        if isinstance(message, app.ToolResultMessage) and not message.tool_call_id:
            raise ValueError("Provider tool messages require tool_call_id")
        if ollama and isinstance(message, app.ToolResultMessage):
            messages.append(
                UserMessage(
                    content=f"[Tool Result] id={message.tool_call_id}\n{message.text}"
                )
            )
        else:
            messages.append(format_provider_message(message))
    if model_needs_formatting_reenabled(config.model_name, config.deployment_name):
        for index, message in enumerate(messages):
            if isinstance(message, SystemMessage):
                messages[index] = SystemMessage(
                    content=CODE_BLOCK_MARKDOWN + message.content
                )
                break
    return messages, cacheable_prefix


def format_provider_message(message: app.Message) -> ChatCompletionMessage:
    """Serialize message content, replaying thinking only when provider signatures exist."""
    if isinstance(message, app.SystemMessage):
        return SystemMessage(content=message.content)
    if isinstance(message, app.UserMessage):
        return UserMessage(content=message.content)
    if isinstance(message, app.AssistantMessage):
        return AssistantMessage(
            content=message.text or None,
            thinking_blocks=message.thinking_blocks,
            tool_calls=[
                ToolCall(
                    id=call.id,
                    function=RequestFunctionCall(
                        name=call.name, arguments=json.dumps(call.arguments)
                    ),
                )
                for call in message.tool_calls
            ]
            or None,
        )
    if isinstance(message, app.ToolResultMessage):
        if not isinstance(message.content, str):
            raise ValueError("Provider tool messages require text content")
        if not message.tool_call_id:
            raise ValueError("Provider tool messages require tool_call_id")
        return ToolMessage(content=message.content, tool_call_id=message.tool_call_id)
    raise TypeError(f"Unsupported message type: {type(message).__name__}")


def serialize_tools(tools: Sequence[app.ToolDefinition]) -> list[dict[str, JsonValue]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
