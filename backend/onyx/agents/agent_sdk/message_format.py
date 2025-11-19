import json
from collections.abc import Sequence
from typing import cast

from langchain.schema.messages import BaseMessage
from langchain_core.messages import AIMessage
from langchain_core.messages import FunctionMessage

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import ImageContent
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import FunctionCall
from onyx.llm.message_types import SystemMessage as ChatSystemMessage
from onyx.llm.message_types import ToolCall
from onyx.llm.message_types import ToolMessage
from onyx.llm.message_types import UserMessageWithText

HUMAN = "human"
SYSTEM = "system"
AI = "ai"
FUNCTION = "function"


# TODO: Currently, we only support native API input for images. For other
# files, we process the content and share it as text in the message. In
# the future, we might support native file uploads for other types of files.
def base_messages_to_agent_sdk_msgs(
    msgs: Sequence[BaseMessage],
    is_responses_api: bool,
) -> list[AgentSDKMessage]:
    return [_base_message_to_agent_sdk_msg(msg, is_responses_api) for msg in msgs]


def base_messages_to_chat_completion_msgs(
    msgs: Sequence[BaseMessage],
) -> list[ChatCompletionMessage]:
    return [_base_message_to_chat_completion_msg(msg) for msg in msgs]


def _base_message_to_agent_sdk_msg(
    msg: BaseMessage, is_responses_api: bool
) -> AgentSDKMessage:
    message_type_to_agent_sdk_role = {
        HUMAN: "user",
        SYSTEM: "system",
        AI: "assistant",
    }
    role = message_type_to_agent_sdk_role[msg.type]

    # Convert content to Agent SDK format
    content = msg.content

    if isinstance(content, str):
        # For system/user/assistant messages, use InputTextContent
        if role in ("system", "user"):
            input_text_content: list[InputTextContent | ImageContent] = [
                InputTextContent(type="input_text", text=content)
            ]
            if role == "system":
                # SystemMessage only accepts InputTextContent
                system_msg: SystemMessage = {
                    "role": "system",
                    "content": [InputTextContent(type="input_text", text=content)],
                }
                return system_msg
            else:  # user
                user_msg: UserMessage = {
                    "role": "user",
                    "content": input_text_content,
                }
                return user_msg
        else:  # assistant
            assistant_msg: AssistantMessageWithContent
            if is_responses_api:
                from onyx.agents.agent_sdk.message_types import OutputTextContent

                assistant_msg = {
                    "role": "assistant",
                    "content": [OutputTextContent(type="output_text", text=content)],
                }
            else:
                assistant_msg = {
                    "role": "assistant",
                    "content": [InputTextContent(type="input_text", text=content)],
                }
            return assistant_msg
    elif isinstance(content, list):
        # For lists, we need to process based on the role
        if role == "assistant":
            # For responses API, use OutputTextContent; otherwise use InputTextContent
            assistant_content: list[InputTextContent | OutputTextContent] = []

            if is_responses_api:
                from onyx.agents.agent_sdk.message_types import OutputTextContent

                for item in content:
                    if isinstance(item, str):
                        assistant_content.append(
                            OutputTextContent(type="output_text", text=item)
                        )
                    elif isinstance(item, dict) and item.get("type") == "text":
                        assistant_content.append(
                            OutputTextContent(
                                type="output_text", text=item.get("text", "")
                            )
                        )
                    else:
                        raise ValueError(
                            f"Unexpected item type for assistant message: {type(item)}. Item: {item}"
                        )
            else:
                for item in content:
                    if isinstance(item, str):
                        assistant_content.append(
                            InputTextContent(type="input_text", text=item)
                        )
                    elif isinstance(item, dict) and item.get("type") == "text":
                        assistant_content.append(
                            InputTextContent(
                                type="input_text", text=item.get("text", "")
                            )
                        )
                    else:
                        raise ValueError(
                            f"Unexpected item type for assistant message: {type(item)}. Item: {item}"
                        )

            assistant_msg_list: AssistantMessageWithContent = {
                "role": "assistant",
                "content": assistant_content,
            }
            return assistant_msg_list
        else:  # system or user - use InputTextContent
            input_content: list[InputTextContent | ImageContent] = []
            for item in content:
                if isinstance(item, str):
                    input_content.append(InputTextContent(type="input_text", text=item))
                elif isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text":
                        input_content.append(
                            InputTextContent(
                                type="input_text", text=item.get("text", "")
                            )
                        )
                    elif item_type == "image_url":
                        # Convert image_url to input_image format
                        image_url = item.get("image_url", {})
                        if isinstance(image_url, dict):
                            url = image_url.get("url", "")
                        else:
                            url = image_url
                        input_content.append(
                            ImageContent(
                                type="input_image", image_url=url, detail="auto"
                            )
                        )
                    else:
                        raise ValueError(f"Unexpected item type: {item_type}")
                else:
                    raise ValueError(
                        f"Unexpected item type: {type(item)}. Item: {item}"
                    )

            if role == "system":
                # SystemMessage only accepts InputTextContent (no images)
                text_only_content = [
                    c for c in input_content if c["type"] == "input_text"
                ]
                system_msg_list: SystemMessage = {
                    "role": "system",
                    "content": text_only_content,  # type: ignore[typeddict-item]
                }
                return system_msg_list
            else:  # user
                user_msg_list: UserMessage = {
                    "role": "user",
                    "content": input_content,
                }
                return user_msg_list
    else:
        raise ValueError(
            f"Unexpected content type: {type(content)}. Content: {content}"
        )


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
