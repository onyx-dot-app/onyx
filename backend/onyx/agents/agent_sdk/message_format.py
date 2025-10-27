from collections.abc import Sequence

from langchain.schema.messages import BaseMessage

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import ImageContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import TextContent
from onyx.agents.agent_sdk.message_types import UserMessage


# TODO: Currently, we only support native API input for images. For other
# files, we process the content and share it as text in the message. In
# the future, we might support native file uploads for other types of files.
def base_messages_to_agent_sdk_msgs(
    msgs: Sequence[BaseMessage],
) -> list[AgentSDKMessage]:
    return [_base_message_to_agent_sdk_msg(msg) for msg in msgs]


def _base_message_to_agent_sdk_msg(msg: BaseMessage) -> AgentSDKMessage:
    message_type_to_agent_sdk_role = {
        "human": "user",
        "system": "system",
        "ai": "assistant",
    }
    role = message_type_to_agent_sdk_role[msg.type]

    # Convert content to Agent SDK format
    content = msg.content
    structured_content: list[TextContent | ImageContent] = []

    if isinstance(content, str):
        # Convert string to structured text format
        text_item: TextContent = {
            "type": "input_text",
            "text": content,
        }
        structured_content = [text_item]
    elif isinstance(content, list):
        # Content is already a list, process each item
        for item in content:
            if isinstance(item, str):
                text_item_from_str: TextContent = {
                    "type": "input_text",
                    "text": item,
                }
                structured_content.append(text_item_from_str)
            elif isinstance(item, dict):
                # Handle different item types
                item_type = item.get("type")

                if item_type == "text":
                    # Convert text type to input_text
                    text_item_from_dict: TextContent = {
                        "type": "input_text",
                        "text": item.get("text", ""),
                    }
                    structured_content.append(text_item_from_dict)
                elif item_type == "image_url":
                    # Convert image_url to input_image format
                    image_url = item.get("image_url", {})
                    if isinstance(image_url, dict):
                        url = image_url.get("url", "")
                    else:
                        url = image_url
                    image_item: ImageContent = {
                        "type": "input_image",
                        "image_url": url,
                        "detail": "auto",
                    }
                    structured_content.append(image_item)
            else:
                raise ValueError(f"Unexpected item type: {type(item)}. Item: {item}")
    else:
        raise ValueError(
            f"Unexpected content type: {type(content)}. Content: {content}"
        )

    # Construct the appropriate message type based on role
    if role == "system":
        system_msg: SystemMessage = {
            "role": "system",
            "content": structured_content,  # type: ignore
        }
        return system_msg
    elif role == "user":
        user_msg: UserMessage = {
            "role": "user",
            "content": structured_content,
        }
        return user_msg
    elif role == "assistant":
        assistant_msg: AssistantMessageWithContent = {
            "role": "assistant",
            "content": structured_content,  # type: ignore
        }
        return assistant_msg
    else:
        raise ValueError(f"Unexpected role: {role}")
