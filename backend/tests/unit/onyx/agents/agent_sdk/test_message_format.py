from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage as LangChainSystemMessage

from onyx.agents.agent_sdk.message_format import base_messages_to_agent_sdk_msgs
from onyx.agents.agent_sdk.message_format import base_messages_to_chat_completion_msgs
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import OutputTextContent
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
    results = base_messages_to_agent_sdk_msgs(messages, is_responses_api=False)

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
    results = base_messages_to_agent_sdk_msgs(messages, is_responses_api=False)

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


def test_assistant_message_non_responses_api() -> None:
    """Test that assistant messages use InputTextContent when is_responses_api=False."""
    # Arrange
    assistant_message = AIMessage(
        content="The capital of France is Paris.",
        additional_kwargs={},
        response_metadata={},
    )

    # Act
    messages = [assistant_message]
    results = base_messages_to_agent_sdk_msgs(messages, is_responses_api=False)

    # Assert
    assert len(results) == 1
    assert results[0].get("role") == "assistant"
    assistant_msg: AssistantMessageWithContent = results[0]  # type: ignore[assignment]
    assert isinstance(assistant_msg["content"], list)
    assert len(assistant_msg["content"]) == 1
    first_content = assistant_msg["content"][0]
    assert first_content["type"] == "input_text"
    text_content: InputTextContent = first_content  # type: ignore[assignment]
    assert text_content["text"] == "The capital of France is Paris."


def test_assistant_message_responses_api() -> None:
    """Test that assistant messages use OutputTextContent when is_responses_api=True."""
    # Arrange
    assistant_message = AIMessage(
        content="The capital of France is Paris.",
        additional_kwargs={},
        response_metadata={},
    )

    # Act
    messages = [assistant_message]
    results = base_messages_to_agent_sdk_msgs(messages, is_responses_api=True)

    # Assert
    assert len(results) == 1
    assert results[0].get("role") == "assistant"
    assistant_msg: AssistantMessageWithContent = results[0]  # type: ignore[assignment]
    assert isinstance(assistant_msg["content"], list)
    assert len(assistant_msg["content"]) == 1
    first_content = assistant_msg["content"][0]
    assert first_content["type"] == "output_text"
    text_content: OutputTextContent = first_content  # type: ignore[assignment]
    assert text_content["text"] == "The capital of France is Paris."


def test_assistant_message_list_content_responses_api() -> None:
    """Test that assistant messages with list content use OutputTextContent when is_responses_api=True."""
    # Arrange
    assistant_message = AIMessage(
        content=[
            {"type": "text", "text": "Paris is the capital."},
            {"type": "text", "text": "It's known for the Eiffel Tower."},
        ],
        additional_kwargs={},
        response_metadata={},
    )

    # Act
    messages = [assistant_message]
    results = base_messages_to_agent_sdk_msgs(messages, is_responses_api=True)

    # Assert
    assert len(results) == 1
    assert results[0].get("role") == "assistant"
    assistant_msg: AssistantMessageWithContent = results[0]  # type: ignore[assignment]
    assert isinstance(assistant_msg["content"], list)
    assert len(assistant_msg["content"]) == 2

    # First item should be output_text
    first_content = assistant_msg["content"][0]
    assert first_content["type"] == "output_text"
    text_content1: OutputTextContent = first_content  # type: ignore[assignment]
    assert text_content1["text"] == "Paris is the capital."

    # Second item should be output_text
    second_content = assistant_msg["content"][1]
    assert second_content["type"] == "output_text"
    text_content2: OutputTextContent = second_content  # type: ignore[assignment]
    assert text_content2["text"] == "It's known for the Eiffel Tower."


def test_assistant_message_list_content_non_responses_api() -> None:
    """Test that assistant messages with list content use InputTextContent when is_responses_api=False."""
    # Arrange
    assistant_message = AIMessage(
        content=[
            {"type": "text", "text": "Paris is the capital."},
            {"type": "text", "text": "It's known for the Eiffel Tower."},
        ],
        additional_kwargs={},
        response_metadata={},
    )

    # Act
    messages = [assistant_message]
    results = base_messages_to_agent_sdk_msgs(messages, is_responses_api=False)

    # Assert
    assert len(results) == 1
    assert results[0].get("role") == "assistant"
    assistant_msg: AssistantMessageWithContent = results[0]  # type: ignore[assignment]
    assert isinstance(assistant_msg["content"], list)
    assert len(assistant_msg["content"]) == 2

    # First item should be input_text
    first_content = assistant_msg["content"][0]
    assert first_content["type"] == "input_text"
    text_content1: InputTextContent = first_content  # type: ignore[assignment]
    assert text_content1["text"] == "Paris is the capital."

    # Second item should be input_text
    second_content = assistant_msg["content"][1]
    assert second_content["type"] == "input_text"
    text_content2: InputTextContent = second_content  # type: ignore[assignment]
    assert text_content2["text"] == "It's known for the Eiffel Tower."


def test_base_messages_to_chat_completion_msgs_basic() -> None:
    """Ensure system and user messages convert to chat completion format."""
    system_message = LangChainSystemMessage(
        content="You are a helpful assistant.",
        additional_kwargs={},
        response_metadata={},
    )
    human_message = HumanMessage(
        content="hello",
        additional_kwargs={},
        response_metadata={},
    )

    results = base_messages_to_chat_completion_msgs([system_message, human_message])

    assert results == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "hello"},
    ]


def test_base_messages_to_chat_completion_msgs_with_tool_call() -> None:
    """Ensure assistant messages with tool calls are preserved."""
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "name": "internal_search",
                "args": {"query": "test"},
            }
        ],
        additional_kwargs={},
        response_metadata={},
    )

    results = base_messages_to_chat_completion_msgs([ai_message])

    assert len(results) == 1
    assert results[0]["role"] == "assistant"
    assert results[0]["tool_calls"][0]["function"]["name"] == "internal_search"
