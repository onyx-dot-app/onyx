"""Integration tests for `POST /chat/file`.

This endpoint exists so chat-only clients can attach files. The Discord bot's
service account holds `write:chat` and nothing more, which is not enough for
`POST /user/projects/file/upload`, so images and PDFs posted in Discord had no
way to reach the agent.
"""

import io

from onyx.auth.schemas import UserRole
from onyx.configs.constants import MessageType
from onyx.server.query_and_chat.models import MessageOrigin
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_file_utils import (
    create_test_image,
    create_test_pdf,
)
from tests.integration.common_utils.test_models import DATestAPIKey, DATestUser

_DUMMY_OPENAI_API_KEY = "sk-mock-chat-file-upload-tests"
_MOCK_ANSWER = "I can see the attachment."


def _chat_only_key_headers(
    admin_user: DATestUser, name: str
) -> tuple[DATestAPIKey, dict[str, str]]:
    """Create a LIMITED service-account key — the Discord bot's exact grant.

    LIMITED keys get `write:chat` (which implies `read:chat`) and nothing else.
    The headers are copied because `APIKeyManager` hands back a shared dict that
    later key creations overwrite.
    """
    api_key = APIKeyManager.create(
        api_key_role=UserRole.LIMITED,
        user_performing_action=admin_user,
        name=name,
    )
    return api_key, {"Authorization": str(api_key.headers["Authorization"])}


def test_chat_file_upload_returns_image_descriptor(admin_user: DATestUser) -> None:
    """An uploaded PNG comes back as an attachable image descriptor."""
    response = FileManager.upload_chat_files(
        files=[("screenshot.png", create_test_image(width=8, height=8, color="blue"))],
        headers=admin_user.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rejected_files"] == []
    assert len(body["files"]) == 1

    descriptor = body["files"][0]
    assert descriptor["type"] == "image"
    assert descriptor["name"] == "screenshot.png"
    assert descriptor["id"]
    assert descriptor["user_file_id"]


def test_chat_file_upload_returns_pdf_descriptor(admin_user: DATestUser) -> None:
    """An uploaded PDF comes back as a document descriptor.

    Documents reach the LLM as extracted text rather than image content, so the
    `document` type is what makes a PDF usable on any model.
    """
    response = FileManager.upload_chat_files(
        files=[("report.pdf", create_test_pdf("Quarterly revenue grew 12 percent"))],
        headers=admin_user.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rejected_files"] == []
    assert len(body["files"]) == 1

    descriptor = body["files"][0]
    assert descriptor["type"] == "document"
    assert descriptor["name"] == "report.pdf"
    assert descriptor["id"]
    assert descriptor["user_file_id"]


def test_chat_file_upload_reports_rejections_per_file(admin_user: DATestUser) -> None:
    """A rejected file must not take the acceptable ones down with it.

    The Discord bot relies on this to tell the agent what it is missing.
    """
    response = FileManager.upload_chat_files(
        files=[
            ("good.png", create_test_image(width=8, height=8)),
            ("good.pdf", create_test_pdf()),
            # Named .png but not actually an image — rejected on content.
            ("broken.png", io.BytesIO(b"definitely not a png")),
            # Named .pdf but has no extractable text — rejected on content.
            ("broken.pdf", io.BytesIO(b"definitely not a pdf")),
        ],
        headers=admin_user.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [file["name"] for file in body["files"]] == ["good.png", "good.pdf"]
    assert [file["filename"] for file in body["rejected_files"]] == [
        "broken.png",
        "broken.pdf",
    ]


def test_chat_scoped_key_can_upload_and_attach(admin_user: DATestUser) -> None:
    """A `write:chat`-only service account can upload files and attach them.

    This is the Discord bot's flow end to end: authenticate with the service
    key, upload the posted image and PDF, then send a non-streaming chat message
    referencing the returned descriptors.
    """
    LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key=_DUMMY_OPENAI_API_KEY,
    )
    _, headers = _chat_only_key_headers(admin_user, "chat_file_upload")

    upload_response = FileManager.upload_chat_files(
        files=[
            ("pasted.png", create_test_image(width=8, height=8, color="red")),
            ("pasted.pdf", create_test_pdf("Quarterly revenue grew 12 percent")),
        ],
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text
    file_descriptors = upload_response.json()["files"]
    assert len(file_descriptors) == 2

    send_response = client.post(
        f"{API_SERVER_URL}/chat/send-chat-message",
        json={
            "message": "What is in these attachments?",
            "stream": False,
            "origin": MessageOrigin.DISCORDBOT.value,
            "file_descriptors": file_descriptors,
            "chat_session_info": {"persona_id": 0},
            "mock_llm_response": _MOCK_ANSWER,
        },
        headers=headers,
    )

    assert send_response.status_code == 200, send_response.text
    body = send_response.json()
    assert body.get("error_msg") is None
    assert body["answer"].strip() == _MOCK_ANSWER

    # Both files are recorded on the persisted user message, which is what makes
    # them visible to the LLM on this turn and any follow-up.
    session_response = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{body['chat_session_id']}",
        headers=headers,
    )
    assert session_response.status_code == 200, session_response.text
    user_messages = [
        message
        for message in session_response.json()["messages"]
        if message["message_type"] == MessageType.USER.value
    ]
    assert len(user_messages) == 1
    attached = user_messages[0]["files"]
    assert {file["name"]: file["type"] for file in attached} == {
        "pasted.png": "image",
        "pasted.pdf": "document",
    }


def test_chat_scoped_key_denied_on_project_upload(admin_user: DATestUser) -> None:
    """The projects upload endpoint stays gated on `basic`."""
    _, headers = _chat_only_key_headers(admin_user, "chat_file_upload_denied")

    response = client.post(
        f"{API_SERVER_URL}/user/projects/file/upload",
        files=[("files", ("pasted.png", create_test_image(), "image/png"))],
        headers=headers,
    )

    assert response.status_code == 403, response.text
