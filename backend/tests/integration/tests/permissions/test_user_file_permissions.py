"""
This file tests user file permissions in different scenarios:
1. Public assistant with user files - files should be accessible to all users
2. Direct file access - user files should NOT be accessible by users who don't own them
3. Image-generation tool outputs - files persisted on `ToolCall.generated_images`
   must be downloadable by the chat session owner (and by anyone if the session
   is publicly shared), but not by other users on private sessions.
"""

import io
from typing import NamedTuple
from uuid import UUID
from uuid import uuid4

import pytest
import requests

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatSession
from onyx.db.models import ToolCall
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestChatSession
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
def user_file_setup(reset: None) -> UserFileTestSetup:  # noqa: ARG001
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
    user_file_id = user1_file_descriptor.get("user_file_id")

    assert user_file_id is not None, "user_file_id should not be None"

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
    assert (
        response.error is None
    ), f"Expected no error when user2 uses public assistant with user1's files, but got error: {response.error}"
    assert len(response.full_message) > 0, "Expected a response from the assistant"

    # Verify chat history is accessible
    chat_history = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=user_file_setup.user2_non_owner,
    )
    assert (
        len(chat_history) >= 2
    ), "Expected at least 2 messages (user message and assistant response)"


def test_cannot_download_other_users_file_via_chat_file_endpoint(
    user_file_setup: UserFileTestSetup,
) -> None:
    storage_file_id = user_file_setup.user1_file_descriptor["id"]
    user_file_id = user_file_setup.user1_file_id

    owner_response = requests.get(
        f"{API_SERVER_URL}/chat/file/{storage_file_id}",
        headers=user_file_setup.user1_file_owner.headers,
    )
    assert owner_response.status_code == 200
    assert owner_response.content, "Owner should receive the file contents"

    for file_id in (storage_file_id, user_file_id):
        user2_response = requests.get(
            f"{API_SERVER_URL}/chat/file/{file_id}",
            headers=user_file_setup.user2_non_owner.headers,
        )
        assert user2_response.status_code in (
            403,
            404,
        ), (
            f"Expected access denied for non-owner, got {user2_response.status_code} "
            f"when fetching file_id={file_id}"
        )
        assert user2_response.content != owner_response.content


# -----------------------------------------------------------------------------
# Image-generation tool output access checks
#
# Image-generation results are persisted on `ToolCall.generated_images` (JSONB),
# *not* on `ChatMessage.files`. The hardening commit `a7a5b66d6` added an
# authorization gate to `GET /chat/file/{file_id}` that did not know about that
# column, so previously-rendered images started returning 404 on chat reload.
# These tests pin the post-fix behavior end-to-end.
# -----------------------------------------------------------------------------


_IMAGE_GEN_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"image-gen-test-bytes"


class ImageGenSetup(NamedTuple):
    owner: DATestUser
    intruder: DATestUser
    chat_session: DATestChatSession
    file_id: str


def _seed_image_gen_tool_call(chat_session_id: UUID) -> str:
    """Persist a fake image to the file store and link it via a ToolCall row,
    mirroring what `ImageGenerationTool` produces at runtime."""
    file_store = get_default_file_store()
    file_id = file_store.save_file(
        content=io.BytesIO(_IMAGE_GEN_PNG_BYTES),
        display_name="GeneratedImage",
        file_origin=FileOrigin.CHAT_IMAGE_GEN,
        file_type="image/png",
    )

    with get_session_with_current_tenant() as db_session:
        tool_call = ToolCall(
            chat_session_id=chat_session_id,
            parent_chat_message_id=None,
            parent_tool_call_id=None,
            turn_number=0,
            tab_index=0,
            tool_id=0,
            tool_call_id=uuid4().hex,
            tool_call_arguments={},
            tool_call_response="",
            tool_call_tokens=0,
            generated_images=[
                {
                    "file_id": file_id,
                    "url": f"/api/chat/file/{file_id}",
                    "revised_prompt": "a cat",
                    "shape": "square",
                }
            ],
        )
        db_session.add(tool_call)
        db_session.commit()

    return file_id


@pytest.fixture
def image_gen_setup(reset: None) -> ImageGenSetup:  # noqa: ARG001
    """Owner with a chat session that has an image-generation tool output."""
    owner: DATestUser = UserManager.create(name="img_gen_owner")
    intruder: DATestUser = UserManager.create(name="img_gen_intruder")
    LLMProviderManager.create(user_performing_action=owner)

    chat_session = ChatSessionManager.create(
        user_performing_action=owner,
        description="image gen permission test",
    )
    file_id = _seed_image_gen_tool_call(UUID(str(chat_session.id)))
    return ImageGenSetup(
        owner=owner,
        intruder=intruder,
        chat_session=chat_session,
        file_id=file_id,
    )


def test_owner_can_download_image_gen_file(
    image_gen_setup: ImageGenSetup,
) -> None:
    """The chat session owner must be able to fetch an image-gen file_id stored
    on `ToolCall.generated_images`. Pre-fix, this returned 404 — that 404 is
    the exact regression these tests pin."""
    response = requests.get(
        f"{API_SERVER_URL}/chat/file/{image_gen_setup.file_id}",
        headers=image_gen_setup.owner.headers,
    )
    assert response.status_code == 200, (
        f"Owner should receive image-gen file, got {response.status_code}: "
        f"{response.text}"
    )
    assert response.content == _IMAGE_GEN_PNG_BYTES


@pytest.mark.skip(
    reason="CHAT_IMAGE_GEN files are temporarily public. See TODO in user_file.py."
)
def test_non_owner_cannot_download_image_gen_file_in_private_session(
    image_gen_setup: ImageGenSetup,
) -> None:
    """A non-owner must not be able to read an image-gen file in a PRIVATE
    session — the new branch should not over-grant access."""
    response = requests.get(
        f"{API_SERVER_URL}/chat/file/{image_gen_setup.file_id}",
        headers=image_gen_setup.intruder.headers,
    )
    assert response.status_code in (403, 404), (
        f"Non-owner should be denied on a private session, got "
        f"{response.status_code}: {response.text}"
    )
    assert response.content != _IMAGE_GEN_PNG_BYTES


def test_non_owner_can_download_image_gen_file_in_public_session(
    image_gen_setup: ImageGenSetup,
) -> None:
    """When the chat session is publicly shared, any authenticated user must
    be able to fetch its image-gen outputs — mirrors the existing
    `ChatMessage.files` public-share branch."""
    with get_session_with_current_tenant() as db_session:
        chat_session = db_session.get(
            ChatSession, UUID(str(image_gen_setup.chat_session.id))
        )
        assert chat_session is not None
        chat_session.shared_status = ChatSessionSharedStatus.PUBLIC
        db_session.commit()

    response = requests.get(
        f"{API_SERVER_URL}/chat/file/{image_gen_setup.file_id}",
        headers=image_gen_setup.intruder.headers,
    )
    assert response.status_code == 200, (
        f"Non-owner should be able to read image-gen file on public session, "
        f"got {response.status_code}: {response.text}"
    )
    assert response.content == _IMAGE_GEN_PNG_BYTES
