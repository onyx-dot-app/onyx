"""
This file tests user file permissions in different scenarios:
1. Public assistant with user files - files should be accessible to all users
2. Direct file access - user files should NOT be accessible by users who don't own them
"""

import io
from typing import NamedTuple

import pytest

from onyx.file_store.models import FileDescriptor
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestPersona
from tests.integration.common_utils.test_models import DATestUser


class UserFileTestSetup(NamedTuple):
    admin_user: DATestUser
    user1_file_owner: DATestUser
    user2_non_owner: DATestUser
    user1_file_descriptor: FileDescriptor
    user1_file_id: str
    public_assistant: DATestPersona


@pytest.fixture
def user_file_setup(reset: None) -> UserFileTestSetup:
    """
    Common setup for user file permission tests.
    Creates users, files, and a public assistant with files.
    """
    # Create an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Create LLM provider for chat functionality
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create user1 who will own the file
    user1: DATestUser = UserManager.create(name="user1_file_owner")

    # Create user2 who will use the assistant but doesn't own the file
    user2: DATestUser = UserManager.create(name="user2_non_owner")

    # Create a test file and upload as user1
    test_file_content = b"This is test content for user file permission checking."
    test_file = ("test_file.txt", io.BytesIO(test_file_content))

    file_descriptors, error = FileManager.upload_files(
        files=[test_file],
        user_performing_action=user1,
    )

    assert not error, f"Failed to upload file: {error}"
    assert len(file_descriptors) == 1, "Expected 1 file to be uploaded"

    # Get the file descriptor and user_file_id
    user1_file_descriptor = file_descriptors[0]
    user_file_id = user1_file_descriptor["user_file_id"]

    # Create a public assistant with the user file attached
    public_assistant = PersonaManager.create(
        name="Public Assistant with Files",
        description="A public assistant with user files for testing permissions",
        is_public=True,
        user_file_ids=[user_file_id],
        user_performing_action=admin_user,
    )

    return UserFileTestSetup(
        admin_user=admin_user,
        user1_file_owner=user1,
        user2_non_owner=user2,
        user1_file_descriptor=user1_file_descriptor,
        user1_file_id=user_file_id,
        public_assistant=public_assistant,
    )


def test_public_assistant_with_user_files(
    user_file_setup: UserFileTestSetup,
) -> None:
    """
    Test that a public assistant with user files attached can be used by users
    who don't own those files without permission errors.
    """
    # Create a chat session with the public assistant as user2
    chat_session = ChatSessionManager.create(
        persona_id=user_file_setup.public_assistant.id,
        description="Test chat session for user file permissions",
        user_performing_action=user_file_setup.user2_non_owner,
    )

    # Send a message as user2 - this should not throw a permission error
    # even though user2 doesn't own the file attached to the assistant
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Hello, can you help me?",
        user_performing_action=user_file_setup.user2_non_owner,
    )

    # Verify the message was processed without errors
    assert response.error is None, (
        f"Expected no error when user2 uses public assistant with user1's files, "
        f"but got error: {response.error}"
    )
    assert len(response.full_message) > 0, "Expected a response from the assistant"

    # Verify chat history is accessible
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=user_file_setup.user2_non_owner,
    )
    assert (
        len(chat_history) >= 2
    ), "Expected at least 2 messages (user message and assistant response)"


def test_user_file_not_accessible_by_other_users(
    user_file_setup: UserFileTestSetup,
) -> None:
    """
    Test that a user file owned by one user cannot be directly used by another user.
    This should throw an error.
    """
    # Create a chat session as user2 with the default assistant
    chat_session = ChatSessionManager.create(
        persona_id=0,  # Default assistant
        description="Test chat session for unauthorized file access",
        user_performing_action=user_file_setup.user2_non_owner,
    )

    # Try to send a message as user2 with user1's file attached
    # This should throw a permission error
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Can you read this file?",
        current_message_files=[user_file_setup.user1_file_descriptor],
        user_performing_action=user_file_setup.user2_non_owner,
    )

    # Verify that an error occurred for unauthorized file access
    assert response.error is not None, (
        "Expected an error when user2 tries to use user1's file directly, "
        "but no error was returned"
    )
