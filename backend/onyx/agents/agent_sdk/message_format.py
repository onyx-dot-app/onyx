from collections.abc import Sequence

from langchain.schema.messages import BaseMessage

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import ImageContent
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import OutputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
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

    if isinstance(content, str):
        # For system/user messages, use InputTextContent; for assistant, use OutputTextContent
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
            assistant_msg: AssistantMessageWithContent = {
                "role": "assistant",
                "content": [OutputTextContent(type="output_text", text=content)],
            }
            return assistant_msg
    elif isinstance(content, list):
        # For lists, we need to process based on the role
        if role == "assistant":
            # Assistant messages use OutputTextContent
            output_content: list[OutputTextContent] = []
            for item in content:
                if isinstance(item, str):
                    output_content.append(
                        OutputTextContent(type="output_text", text=item)
                    )
                elif isinstance(item, dict) and item.get("type") == "text":
                    output_content.append(
                        OutputTextContent(type="output_text", text=item.get("text", ""))
                    )
                else:
                    raise ValueError(
                        f"Unexpected item type for assistant message: {type(item)}. Item: {item}"
                    )
            assistant_msg_list: AssistantMessageWithContent = {
                "role": "assistant",
                "content": output_content,
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
