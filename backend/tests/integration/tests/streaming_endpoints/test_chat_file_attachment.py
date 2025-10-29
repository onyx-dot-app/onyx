from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_file_utils import create_test_image
from tests.integration.common_utils.test_file_utils import create_test_text_file
from tests.integration.common_utils.test_models import DATestUser


def test_send_message_with_image_attachment(admin_user: DATestUser) -> None:
    """Test sending a chat message with an attached image file."""
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create a simple test image
    image_file = create_test_image(width=100, height=100, color="blue")

    # Upload the image file
    file_descriptors, error = FileManager.upload_files(
        files=[("test_image.png", image_file)],
        user_performing_action=admin_user,
    )

    assert not error, f"File upload should succeed, but got error: {error}"
    assert len(file_descriptors) == 1, "Should have uploaded one file"
    assert file_descriptors[0]["type"] == "image", "File should be identified as image"

    # Create a chat session
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    # Send a message with the image attachment
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="What color is this image?",
        user_performing_action=admin_user,
        file_descriptors=file_descriptors,
    )

    # Verify that the message was processed successfully
    assert response.error is None, "Chat response should not have an error"
    assert (
        "blue" in response.full_message.lower()
    ), "Chat response should contain the color of the image"


def test_send_message_with_text_file_attachment(admin_user: DATestUser) -> None:
    """Test sending a chat message with an attached text file."""
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create a simple test text file
    text_file = create_test_text_file(
        "This is a test document.\nIt has multiple lines.\nThis is the third line."
    )

    # Upload the text file
    file_descriptors, error = FileManager.upload_files(
        files=[("test_document.txt", text_file)],
        user_performing_action=admin_user,
    )

    assert not error, f"File upload should succeed, but got error: {error}"
    assert len(file_descriptors) == 1, "Should have uploaded one file"
    assert file_descriptors[0]["type"] in [
        "plain_text",
        "document",
    ], "File should be identified as text or document"

    # Create a chat session
    test_chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    # Send a message with the text file attachment
    response = ChatSessionManager.send_message(
        chat_session_id=test_chat_session.id,
        message="Repeat the contents of this file word for word.",
        user_performing_action=admin_user,
        file_descriptors=file_descriptors,
    )

    # Verify that the message was processed successfully
    assert response.error is None, "Chat response should not have an error"
    assert (
        "third line" in response.full_message.lower()
    ), "Chat response should contain the contents of the file"
