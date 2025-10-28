from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage as LangChainSystemMessage

from onyx.agents.agent_sdk.message_format import base_messages_to_agent_sdk_msgs
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage as AgentSDKSystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage


def test_simple_text_human_message() -> None:
    """Test conversion of HumanMessage with simple text content."""
    # Arrange
    human_message = HumanMessage(
        content="What is the capital of France?",
        additional_kwargs={},
        response_metadata={},
    )

    # Act
    messages = [human_message]
    results = base_messages_to_agent_sdk_msgs(messages)

    # Assert
    assert len(results) == 1
    assert results[0].get("role") == "user"
    # Type narrow after checking role
    user_msg: UserMessage = results[0]  # type: ignore[assignment]
    assert isinstance(user_msg["content"], list)
    assert len(user_msg["content"]) == 1
    first_content = user_msg["content"][0]
    assert first_content["type"] == "input_text"
    text_content: InputTextContent = first_content  # type: ignore[assignment]
    assert text_content["text"] == "What is the capital of France?"


def test_base_messages_to_agent_sdk_msgs() -> None:
    """Test conversion of SystemMessage and HumanMessage with multimodal content (text + image)."""
    # Arrange
    system_message = LangChainSystemMessage(
        content="You are a highly capable, thoughtful, and precise assistant..",
        additional_kwargs={},
        response_metadata={},
    )

    human_message = HumanMessage(
        content=[
            {"type": "text", "text": "what's in this screenshot"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,iVBORw0KGg"},
            },
        ],
        additional_kwargs={},
        response_metadata={},
    )

    # Act
    messages = [system_message, human_message]
    results = base_messages_to_agent_sdk_msgs(messages)

    # Assert - System message
    assert results[0].get("role") == "system"
    system_msg: AgentSDKSystemMessage = results[0]  # type: ignore[assignment]
    assert isinstance(system_msg["content"], list)
    assert len(system_msg["content"]) == 1
    first_content = system_msg["content"][0]
    assert first_content["type"] == "input_text"
    text_content: InputTextContent = first_content  # type: ignore[assignment]
    assert "You are a highly capable" in text_content["text"]

    # Assert - User message
    assert results[1].get("role") == "user"
    user_msg: UserMessage = results[1]  # type: ignore[assignment]
    assert isinstance(user_msg["content"], list)
    assert len(user_msg["content"]) == 2

    # First item should be text
    first_item = user_msg["content"][0]
    assert first_item["type"] == "input_text"
    text_item: InputTextContent = first_item  # type: ignore[assignment]
    assert text_item["text"] == "what's in this screenshot"

    # Second item should be image
    second_item = user_msg["content"][1]
    assert second_item["type"] == "input_image"
    # Since we know it's input_image type, we can access image-specific fields
    # but need type: ignore since mypy doesn't narrow unions automatically
    assert second_item["image_url"].startswith("data:image/png;base64")  # type: ignore[typeddict-item]
    assert second_item["detail"] == "auto"  # type: ignore[typeddict-item]
