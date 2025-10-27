from collections.abc import Sequence

from langchain.schema.messages import BaseMessage


# TODO: Currently, we only support native API input for images. For other
# files, we process the content and share it as text in the message. In
# the future, we might support native file uploads for other types of files.
def base_messages_to_agent_sdk_msgs(msgs: Sequence[BaseMessage]) -> list[dict]:
    return [_base_message_to_agent_sdk_msg(msg) for msg in msgs]


def _base_message_to_agent_sdk_msg(msg: BaseMessage) -> dict:
    message_type_to_agent_sdk_role = {
        "human": "user",
        "system": "system",
        "ai": "assistant",
    }
    role = message_type_to_agent_sdk_role[msg.type]

    # Convert content to Agent SDK format
    content = msg.content
    if isinstance(content, str):
        # Convert string to structured text format
        structured_content = [
            {
                "type": "input_text",
                "text": content,
            }
        ]
    elif isinstance(content, list):
        # Content is already a list, process each item
        structured_content = []
        for item in content:
            if isinstance(item, str):
                structured_content.append(
                    {
                        "type": "input_text",
                        "text": item,
                    }
                )
            elif isinstance(item, dict):
                # Handle different item types
                item_type = item.get("type")

                if item_type == "text":
                    # Convert text type to input_text
                    structured_content.append(
                        {
                            "type": "input_text",
                            "text": item.get("text", ""),
                        }
                    )
                elif item_type == "image_url":
                    # Convert image_url to input_image format
                    image_url = item.get("image_url", {})
                    if isinstance(image_url, dict):
                        url = image_url.get("url", "")
                    else:
                        url = image_url
                    structured_content.append(
                        {
                            "type": "input_image",
                            "image_url": url,
                            "detail": "auto",
                        }
                    )
            else:
                raise ValueError(f"Unexpected item type: {type(item)}. Item: {item}")
    else:
        raise ValueError(
            f"Unexpected content type: {type(content)}. Content: {content}"
        )

    return {
        "role": role,
        "content": structured_content,
    }
