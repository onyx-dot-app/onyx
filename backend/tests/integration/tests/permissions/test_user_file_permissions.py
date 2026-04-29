"""
This file tests user file permissions in different scenarios:
1. Public assistant with user files - files should be accessible to all users
2. Direct file access - user files should NOT be accessible by users who don't own them
3. Image-generation tool outputs - files persisted on `ToolCall.generated_images`
   must be downloadable by the chat session owner (and by anyone if the session
   is publicly shared), but not by other users on private sessions.
4. Connector-ingested files - files stored with `FileOrigin.CONNECTOR` must be
   fetchable via `GET /chat/file/{file_id}` by any user whose ACL covers at
   least one `Document` that references the file, and must be denied otherwise.
"""

import io
from typing import NamedTuple
from uuid import UUID
from uuid import uuid4

import pytest
import requests

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import ChatSessionSharedStatus
from onyx.db.models import ChatSession
from onyx.db.models import Document
from onyx.db.models import ToolCall
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestCCPair
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


_CONNECTOR_FILE_BYTES = b"connector-ingested document contents"


def _seed_connector_file(
    *,
    document_id: str,
    file_origin: FileOrigin = FileOrigin.CONNECTOR,
) -> str:
    """Save bytes and link `Document.file_id` to the storage id, exercising
    the fast path in `_user_can_access_connector_file`."""
    file_store = get_default_file_store()
    storage_id = file_store.save_file(
        content=io.BytesIO(_CONNECTOR_FILE_BYTES),
        display_name="connector_doc.txt",
        file_origin=file_origin,
        file_type="text/plain",
    )
    with get_session_with_current_tenant() as db_session:
        document = db_session.get(Document, document_id)
        assert document is not None, f"Seeded document {document_id} not found"
        document.file_id = storage_id
        db_session.commit()
    return storage_id


# Origins that connector-ingested files have carried in prod: pipeline-
# promoted (`CONNECTOR`), modern admin upload (`CONNECTOR_FILE_UPLOAD`,
# added in #10484), and legacy admin upload (`OTHER`, pre-#10484). The
# access check ignores origin, but parametrizing here guards against a
# regression that re-introduces an origin filter.
_CONNECTOR_FILE_ORIGINS = [
    FileOrigin.CONNECTOR,
    FileOrigin.CONNECTOR_FILE_UPLOAD,
    FileOrigin.OTHER,
]


@pytest.mark.parametrize("file_origin", _CONNECTOR_FILE_ORIGINS)
def test_connector_file_is_accessible_via_chat_file_endpoint(
    reset: None,  # noqa: ARG001
    file_origin: FileOrigin,
) -> None:
    """Regression test for #10472: PUBLIC connector file is fetchable by
    any authenticated user via `/chat/file/{file_id}`, regardless of
    `FileOrigin` stamp."""
    admin_user: DATestUser = UserManager.create(name="connector_admin")
    basic_user: DATestUser = UserManager.create(name="connector_basic")

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    public_cc_pair = CCPairManager.create_from_scratch(
        access_type=AccessType.PUBLIC,
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    document = DocumentManager.seed_doc_with_content(
        cc_pair=public_cc_pair,
        content="hello from connector",
        api_key=api_key,
    )
    storage_id = _seed_connector_file(
        document_id=document.id,
        file_origin=file_origin,
    )

    for user in (admin_user, basic_user):
        response = requests.get(
            f"{API_SERVER_URL}/chat/file/{storage_id}",
            headers=user.headers,
        )
        assert response.status_code == 200, (
            f"User {user.email} must be able to fetch a PUBLIC connector file "
            f"(origin={file_origin}), got {response.status_code}: {response.text}"
        )
        assert response.content == _CONNECTOR_FILE_BYTES


@pytest.mark.parametrize("file_origin", _CONNECTOR_FILE_ORIGINS)
def test_connector_file_denied_for_users_without_access(
    reset: None,  # noqa: ARG001
    file_origin: FileOrigin,
) -> None:
    """Flip side: a PRIVATE cc_pair connector file stays denied for users
    with no ACL overlap, across every historical `FileOrigin` stamp."""
    admin_user: DATestUser = UserManager.create(name="priv_connector_admin")
    basic_user: DATestUser = UserManager.create(name="priv_connector_basic")

    api_key = APIKeyManager.create(user_performing_action=admin_user)
    private_cc_pair = CCPairManager.create_from_scratch(
        access_type=AccessType.PRIVATE,
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    document = DocumentManager.seed_doc_with_content(
        cc_pair=private_cc_pair,
        content="private connector content",
        api_key=api_key,
    )
    storage_id = _seed_connector_file(
        document_id=document.id,
        file_origin=file_origin,
    )

    basic_response = requests.get(
        f"{API_SERVER_URL}/chat/file/{storage_id}",
        headers=basic_user.headers,
    )
    assert basic_response.status_code in (403, 404), (
        f"Non-member should be denied on PRIVATE connector file "
        f"(origin={file_origin}), got {basic_response.status_code}: "
        f"{basic_response.text}"
    )
    assert basic_response.content != _CONNECTOR_FILE_BYTES


# Non-tabular File-connector uploads (txt/pdf/docx/...) leave
# `Document.file_id=NULL` (see `connectors/file/connector.py`), so the fast
# path misses and access falls back to matching against
# `Connector.connector_specific_config['file_locations']`. These tests pin
# that fallback. `CONNECTOR` is excluded because pipeline-promoted files
# always get `Document.file_id` stamped and so never hit the fallback.
_NON_TABULAR_FILE_ORIGINS = [
    FileOrigin.CONNECTOR_FILE_UPLOAD,
    FileOrigin.OTHER,
]


def _seed_non_tabular_file_connector_cc_pair(
    *,
    admin_user: DATestUser,
    file_id: str,
    access_type: AccessType,
    groups: list[int] | None = None,
) -> DATestCCPair:
    """Build a File-source cc_pair pointing at `file_id` without setting
    `Document.file_id` — mirrors a non-tabular upload."""
    return CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [file_id],
            "file_names": ["non_tabular.txt"],
            "zip_metadata_file_id": None,
        },
        access_type=access_type,
        groups=groups,
    )


def _save_non_tabular_file_bytes(file_id: str, file_origin: FileOrigin) -> None:
    """Save bytes under the exact `file_id` listed in the cc_pair's
    `file_locations`. Can't reuse `_seed_connector_file` because that
    stamps `Document.file_id` and would bypass the fallback under test."""
    file_store = get_default_file_store()
    file_store.save_file(
        content=io.BytesIO(_CONNECTOR_FILE_BYTES),
        display_name="non_tabular.txt",
        file_origin=file_origin,
        file_type="text/plain",
        file_id=file_id,
    )


@pytest.mark.parametrize("file_origin", _NON_TABULAR_FILE_ORIGINS)
def test_non_tabular_connector_file_is_accessible_via_chat_file_endpoint(
    reset: None,  # noqa: ARG001
    file_origin: FileOrigin,
) -> None:
    """PUBLIC non-tabular File-connector upload: the JSONB fallback in
    `_user_can_access_connector_file` lets any user fetch it."""
    admin_user: DATestUser = UserManager.create(name="non_tabular_admin")
    basic_user: DATestUser = UserManager.create(name="non_tabular_basic")
    api_key = APIKeyManager.create(user_performing_action=admin_user)

    file_id = str(uuid4())
    public_cc_pair = _seed_non_tabular_file_connector_cc_pair(
        admin_user=admin_user,
        file_id=file_id,
        access_type=AccessType.PUBLIC,
    )

    # Document ingested against the cc_pair without `file_id` — the
    # "non-tabular" case under test.
    DocumentManager.seed_doc_with_content(
        cc_pair=public_cc_pair,
        content="non-tabular body text",
        api_key=api_key,
    )
    _save_non_tabular_file_bytes(file_id, file_origin)

    for user in (admin_user, basic_user):
        response = requests.get(
            f"{API_SERVER_URL}/chat/file/{file_id}",
            headers=user.headers,
        )
        assert response.status_code == 200, (
            f"User {user.email} must access a PUBLIC File-connector non-tabular "
            f"file (origin={file_origin}), got {response.status_code}: "
            f"{response.text}"
        )
        assert response.content == _CONNECTOR_FILE_BYTES


@pytest.mark.parametrize("file_origin", _NON_TABULAR_FILE_ORIGINS)
def test_non_tabular_connector_file_denied_for_users_without_access(
    reset: None,  # noqa: ARG001
    file_origin: FileOrigin,
) -> None:
    """PRIVATE non-tabular File-connector upload: ACL still gates access
    even though the JSONB fallback locates the file."""
    admin_user: DATestUser = UserManager.create(name="non_tabular_priv_admin")
    basic_user: DATestUser = UserManager.create(name="non_tabular_priv_basic")
    api_key = APIKeyManager.create(user_performing_action=admin_user)

    file_id = str(uuid4())
    private_cc_pair = _seed_non_tabular_file_connector_cc_pair(
        admin_user=admin_user,
        file_id=file_id,
        access_type=AccessType.PRIVATE,
    )
    DocumentManager.seed_doc_with_content(
        cc_pair=private_cc_pair,
        content="non-tabular private content",
        api_key=api_key,
    )
    _save_non_tabular_file_bytes(file_id, file_origin)

    basic_response = requests.get(
        f"{API_SERVER_URL}/chat/file/{file_id}",
        headers=basic_user.headers,
    )
    assert basic_response.status_code in (403, 404), (
        f"Non-member should be denied on PRIVATE non-tabular connector file "
        f"(origin={file_origin}), got {basic_response.status_code}: "
        f"{basic_response.text}"
    )
    assert basic_response.content != _CONNECTOR_FILE_BYTES
