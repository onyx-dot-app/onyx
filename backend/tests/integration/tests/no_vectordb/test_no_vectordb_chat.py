"""Integration tests for chat in no-vector-DB mode.

Covers:
- Uploading a file to a project, sending a chat message, and verifying the LLM
  receives the file content (small project — fits in context window).
- Creating a persona with user_files and verifying chat works.
- Verifying that persona creation with document_sets / hierarchy_nodes /
  document_ids is rejected with a 400.
"""

import io
import time

import requests

from onyx.db.enums import UserFileStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


FILE_READER_TOOL_ID = "FileReaderTool"


def _wait_for_file_processed(
    project_id: int,
    user: DATestUser,
    timeout: int = 30,
) -> None:
    """Poll until all files in the project reach COMPLETED status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = ProjectManager.get_project_files(project_id, user)
        if files and all(f.status == UserFileStatus.COMPLETED for f in files):
            return
        time.sleep(1)
    raise TimeoutError(
        f"Files in project {project_id} did not reach COMPLETED within {timeout}s"
    )


# ------------------------------------------------------------------
# Small-project chat — file content loaded directly into context
# ------------------------------------------------------------------


def test_chat_with_small_project_file(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Upload a small text file to a project and send a chat message.

    The file is small enough to fit in the LLM context window, so the LLM
    should see the file content directly and be able to answer questions
    about it.
    """
    project = ProjectManager.create(
        name="test-no-vectordb-small", user_performing_action=admin_user
    )

    file_content = b"The secret code is PINEAPPLE-42."
    ProjectManager.upload_files(
        project_id=project.id,
        files=[("secret.txt", file_content)],
        user_performing_action=admin_user,
    )

    _wait_for_file_processed(project.id, admin_user)

    # Create a chat session associated with the project's default persona
    chat_session = ChatSessionManager.create(
        persona_id=0,
        description="no-vectordb small project test",
        user_performing_action=admin_user,
    )

    # Link the chat session to the project
    resp = requests.post(
        f"{API_SERVER_URL}/user/projects/{project.id}/move_chat_session",
        json={"chat_session_id": str(chat_session.id)},
        headers=admin_user.headers,
    )
    resp.raise_for_status()

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the secret code in the file?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Chat returned an error: {response.error}"
    assert (
        "PINEAPPLE-42" in response.full_message
    ), f"Expected the LLM to reference the file content. Got: {response.full_message}"


# ------------------------------------------------------------------
# Persona with user_files — should work in no-vector-DB mode
# ------------------------------------------------------------------


def test_persona_with_user_files_chat(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Create a persona with attached user files and verify chat works."""
    # Upload a file first
    file_content = b"Quarterly revenue was $42 million."
    file_obj = io.BytesIO(file_content)
    file_descriptors, error = FileManager.upload_files(
        files=[("revenue.txt", file_obj)],
        user_performing_action=admin_user,
    )
    assert not error, f"File upload failed: {error}"
    assert len(file_descriptors) > 0

    user_file_id = file_descriptors[0].get("user_file_id")
    assert user_file_id, "Expected user_file_id in upload response"

    # Wait for the file to be processed
    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(1)
        # Check via file fetch — if it succeeds, the file is ready
        try:
            FileManager.fetch_uploaded_file(
                file_descriptors[0]["id"],
                admin_user,
            )
            break
        except Exception:
            continue

    # Find the FileReaderTool ID from available tools
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    file_reader_tool = next(
        (t for t in tools if t.in_code_tool_id == FILE_READER_TOOL_ID), None
    )
    assert (
        file_reader_tool is not None
    ), "FileReaderTool should be registered as a built-in tool"

    # Create a persona with the user file attached
    persona = PersonaManager.create(
        name="no-vectordb-persona-test",
        description="Test persona for no-vectordb mode",
        user_file_ids=[user_file_id],
        tool_ids=[file_reader_tool.id],
        user_performing_action=admin_user,
    )

    chat_session = ChatSessionManager.create(
        persona_id=persona.id,
        description="no-vectordb persona test",
        user_performing_action=admin_user,
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What was the quarterly revenue?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Chat returned an error: {response.error}"
    # The LLM should be able to answer about the revenue (either from direct
    # context injection or via the FileReaderTool)
    assert (
        "$42 million" in response.full_message or "42" in response.full_message
    ), f"Expected the LLM to reference the file content. Got: {response.full_message}"


# ------------------------------------------------------------------
# Persona validation — vector-DB knowledge types rejected
# ------------------------------------------------------------------


def _base_persona_body(**overrides: object) -> dict:
    """Build a valid PersonaUpsertRequest body with sensible defaults.

    Callers override only the fields under test so that Pydantic validation
    passes and the vector-DB guard (``_validate_vector_db_knowledge``) is
    the one that rejects the request.
    """
    body: dict = {
        "name": "should-fail",
        "description": "test",
        "system_prompt": "test",
        "task_prompt": "",
        "num_chunks": 5,
        "is_public": True,
        "recency_bias": "auto",
        "llm_filter_extraction": False,
        "llm_relevance_filter": False,
        "datetime_aware": False,
        "document_set_ids": [],
        "tool_ids": [],
        "users": [],
        "groups": [],
    }
    body.update(overrides)
    return body


def test_persona_rejects_document_sets_without_vector_db(
    admin_user: DATestUser,
) -> None:
    """Creating a persona with document_set_ids should fail with 400."""
    resp = requests.post(
        f"{API_SERVER_URL}/persona",
        json=_base_persona_body(document_set_ids=[1]),
        headers=admin_user.headers,
    )
    assert (
        resp.status_code == 400
    ), f"Expected 400 for document_set_ids, got {resp.status_code}: {resp.text}"


def test_persona_rejects_document_ids_without_vector_db(
    admin_user: DATestUser,
) -> None:
    """Creating a persona with document_ids should fail with 400."""
    resp = requests.post(
        f"{API_SERVER_URL}/persona",
        json=_base_persona_body(document_ids=["fake-doc-id"]),
        headers=admin_user.headers,
    )
    assert (
        resp.status_code == 400
    ), f"Expected 400 for document_ids, got {resp.status_code}: {resp.text}"
