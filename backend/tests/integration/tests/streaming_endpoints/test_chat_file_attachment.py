import mimetypes
from typing import Any

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
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


def _set_token_threshold(admin_user: DATestUser, threshold_k: int) -> None:
    """Set the file token count threshold via admin settings API."""
    response = requests.put(
        f"{API_SERVER_URL}/admin/settings",
        json={"file_token_count_threshold_k": threshold_k},
        headers=admin_user.headers,
    )
    response.raise_for_status()


def _upload_raw(
    filename: str,
    content: bytes,
    user: DATestUser,
) -> dict[str, Any]:
    """Upload a file and return the full JSON response (user_files + rejected_files)."""
    mime_type, _ = mimetypes.guess_type(filename)
    headers = user.headers.copy()
    headers.pop("Content-Type", None)

    response = requests.post(
        f"{API_SERVER_URL}/user/projects/file/upload",
        files=[("files", (filename, content, mime_type or "application/octet-stream"))],
        headers=headers,
    )
    response.raise_for_status()
    return response.json()


def test_csv_over_token_threshold_uploaded_not_indexed(
    admin_user: DATestUser,
) -> None:
    """CSV exceeding token threshold is uploaded (accepted) but skips indexing."""
    _set_token_threshold(admin_user, threshold_k=1)
    try:
        # ~2000 tokens with default tokenizer, well over 1K threshold
        content = ("x " * 100 + "\n") * 20
        result = _upload_raw("large.csv", content.encode(), admin_user)

        assert len(result["user_files"]) == 1, "CSV should be accepted"
        assert len(result["rejected_files"]) == 0, "CSV should not be rejected"
        assert (
            result["user_files"][0]["status"] == "SKIPPED"
        ), "CSV over threshold should be SKIPPED (uploaded but not indexed)"
        assert (
            result["user_files"][0]["chunk_count"] is None
        ), "Skipped file should have no chunks"
    finally:
        _set_token_threshold(admin_user, threshold_k=200)


def test_csv_under_token_threshold_uploaded_and_indexed(
    admin_user: DATestUser,
) -> None:
    """CSV under token threshold is uploaded and queued for indexing."""
    _set_token_threshold(admin_user, threshold_k=200)
    try:
        content = "col1,col2\na,b\n"
        result = _upload_raw("small.csv", content.encode(), admin_user)

        assert len(result["user_files"]) == 1, "CSV should be accepted"
        assert len(result["rejected_files"]) == 0, "CSV should not be rejected"
        assert (
            result["user_files"][0]["status"] == "PROCESSING"
        ), "CSV under threshold should be PROCESSING (queued for indexing)"
    finally:
        _set_token_threshold(admin_user, threshold_k=200)


def test_txt_over_token_threshold_rejected(
    admin_user: DATestUser,
) -> None:
    """Non-exempt file exceeding token threshold is rejected entirely."""
    _set_token_threshold(admin_user, threshold_k=1)
    try:
        # ~2000 tokens, well over 1K threshold. Unlike CSV, .txt is not
        # exempt from the threshold so the file should be rejected.
        content = ("x " * 100 + "\n") * 20
        result = _upload_raw("big.txt", content.encode(), admin_user)

        assert len(result["user_files"]) == 0, "File should not be accepted"
        assert len(result["rejected_files"]) == 1, "File should be rejected"
        assert "token limit" in result["rejected_files"][0]["reason"].lower()
    finally:
        _set_token_threshold(admin_user, threshold_k=200)
