import json
from collections.abc import Sequence
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import FunctionMessage

from onyx.agents.agent_sdk.message_format import ChatSystemMessage
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import FunctionCall
from onyx.llm.message_types import ToolCall
from onyx.llm.message_types import ToolMessage
from onyx.llm.message_types import UserMessageWithText


HUMAN = "human"
SYSTEM = "system"
AI = "ai"
FUNCTION = "function"


def base_messages_to_chat_completion_msgs(
    msgs: Sequence[BaseMessage],
) -> list[ChatCompletionMessage]:
    return [_base_message_to_chat_completion_msg(msg) for msg in msgs]


def _base_message_to_chat_completion_msg(
    msg: BaseMessage,
) -> ChatCompletionMessage:
    if msg.type == HUMAN:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        user_msg: UserMessageWithText = {"role": "user", "content": content}
        return user_msg
    if msg.type == SYSTEM:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        system_msg: ChatSystemMessage = {"role": "system", "content": content}
        return system_msg
    if msg.type == AI:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        assistant_msg: AssistantMessage = {
            "role": "assistant",
            "content": content,
        }
        if isinstance(msg, AIMessage) and msg.tool_calls:
            assistant_msg["tool_calls"] = [
                ToolCall(
                    id=tool_call.get("id") or "",
                    type="function",
                    function=FunctionCall(
                        name=tool_call["name"],
                        arguments=json.dumps(tool_call["args"]),
                    ),
                )
                for tool_call in msg.tool_calls
            ]
        return assistant_msg
    if msg.type == FUNCTION:
        function_message = cast(FunctionMessage, msg)
        content = (
            function_message.content
            if isinstance(function_message.content, str)
            else str(function_message.content)
        )
        tool_msg: ToolMessage = {
            "role": "tool",
            "content": content,
            "tool_call_id": function_message.name or "",
        }
        return tool_msg
    raise ValueError(f"Unexpected message type: {msg.type}")
