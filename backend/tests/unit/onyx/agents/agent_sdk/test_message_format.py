from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from onyx.agents.agent_sdk.message_format import base_messages_to_agent_sdk_msgs


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
    assert results[0]["role"] == "user"
    assert isinstance(results[0]["content"], list)
    assert len(results[0]["content"]) == 1
    assert results[0]["content"][0]["type"] == "input_text"
    assert results[0]["content"][0]["text"] == "What is the capital of France?"


def test_base_messages_to_agent_sdk_msgs() -> None:
    """Test conversion of SystemMessage and HumanMessage with multimodal content (text + image)."""
    # Arrange
    system_message = SystemMessage(
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
    # Assert
    assert results[0]["role"] == "system"
    assert isinstance(results[0]["content"], list)
    assert len(results[0]["content"]) == 1
    assert results[0]["content"][0]["type"] == "input_text"
    assert "You are a highly capable" in results[0]["content"][0]["text"]

    assert results[1]["role"] == "user"
    assert isinstance(results[1]["content"], list)
    assert len(results[1]["content"]) == 2

    # First item should be text
    assert results[1]["content"][0]["type"] == "input_text"
    assert results[1]["content"][0]["text"] == "what's in this screenshot"

    # Second item should be image_url
    assert results[1]["content"][1]["type"] == "input_image"
    assert results[1]["content"][1]["image_url"].startswith("data:image/png;base64")
    assert results[1]["content"][1]["detail"] == "auto"
