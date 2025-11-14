from collections.abc import Sequence

from langchain.schema.messages import BaseMessage

from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import ContentPart
from onyx.llm.message_types import ImageContentPart
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import TextContentPart
from onyx.llm.message_types import UserMessageWithParts
from onyx.llm.message_types import UserMessageWithText


def base_messages_to_chat_completion_msgs(
    msgs: Sequence[BaseMessage],
) -> list[ChatCompletionMessage]:
    return [_base_message_to_chat_completion_msg(msg) for msg in msgs]


def _base_message_to_chat_completion_msg(msg: BaseMessage) -> ChatCompletionMessage:
    message_type_to_role = {
        "human": "user",
        "system": "system",
        "ai": "assistant",
        "tool": "tool",
    }
    role = message_type_to_role[msg.type]

    content = msg.content

    if isinstance(content, str):
        # Simple string content
        if role == "system":
            system_msg: SystemMessage = {
                "role": "system",
                "content": content,
            }
            return system_msg
        elif role == "user":
            user_msg: UserMessageWithText = {
                "role": "user",
                "content": content,
            }
            return user_msg
        else:  # assistant
            assistant_msg: AssistantMessage = {
                "role": "assistant",
                "content": content,
            }
            return assistant_msg

    elif isinstance(content, list):
        # List content - need to convert to OpenAI format
        if role == "assistant":
            # For assistant, convert list to simple string
            # (OpenAI format uses string content, not list)
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                else:
                    raise ValueError(
                        f"Unexpected item type for assistant message: {type(item)}. Item: {item}"
                    )

            assistant_msg_from_list: AssistantMessage = {
                "role": "assistant",
                "content": " ".join(text_parts) if text_parts else None,
            }
            return assistant_msg_from_list

        else:  # system or user
            content_parts: list[ContentPart] = []
            has_images = False

            for item in content:
                if isinstance(item, str):
                    content_parts.append(TextContentPart(type="text", text=item))
                elif isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text":
                        content_parts.append(
                            TextContentPart(type="text", text=item.get("text", ""))
                        )
                    elif item_type == "image_url":
                        has_images = True
                        # Convert image_url to OpenAI format
                        image_url = item.get("image_url", {})
                        if isinstance(image_url, dict):
                            url = image_url.get("url", "")
                            detail = image_url.get("detail", "auto")
                        else:
                            url = image_url
                            detail = "auto"

                        image_part: ImageContentPart = {
                            "type": "image_url",
                            "image_url": {"url": url, "detail": detail},
                        }
                        content_parts.append(image_part)
                    else:
                        raise ValueError(f"Unexpected item type: {item_type}")
                else:
                    raise ValueError(
                        f"Unexpected item type: {type(item)}. Item: {item}"
                    )

            if role == "system":
                # System messages should be text only, concatenate all text parts
                text_parts = [
                    part["text"] for part in content_parts if part["type"] == "text"
                ]
                system_msg_from_list: SystemMessage = {
                    "role": "system",
                    "content": " ".join(text_parts),
                }
                return system_msg_from_list
            else:  # user
                # If there are images, use the parts format; otherwise use simple string
                if has_images or len(content_parts) > 1:
                    user_msg_with_parts: UserMessageWithParts = {
                        "role": "user",
                        "content": content_parts,
                    }
                    return user_msg_with_parts
                elif len(content_parts) == 1 and content_parts[0]["type"] == "text":
                    # Single text part - use simple string format
                    user_msg_simple: UserMessageWithText = {
                        "role": "user",
                        "content": content_parts[0]["text"],
                    }
                    return user_msg_simple
                else:
                    # Empty content
                    user_msg_empty: UserMessageWithText = {
                        "role": "user",
                        "content": "",
                    }
                    return user_msg_empty
    else:
        raise ValueError(
            f"Unexpected content type: {type(content)}. Content: {content}"
        )
