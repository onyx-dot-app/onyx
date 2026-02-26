"""
Integration tests for the unified persona file context flow.

End-to-end tests that verify:
1. Files can be uploaded and attached to a persona via API.
2. The persona correctly reports its attached files.
3. A chat session with a file-bearing persona processes without error.
4. Precedence: custom persona files take priority over project files when
   the chat session is inside a project.

These tests run against a real Onyx deployment (all services running).
File processing is asynchronous, so we poll the file status endpoint
until files reach COMPLETED before chatting.
"""

import time

import requests

from onyx.db.enums import UserFileStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.test_file_utils import create_test_text_file
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILE_PROCESSING_POLL_INTERVAL = 2


def _poll_file_statuses(
    user_file_ids: list[str],
    user: DATestUser,
    target_status: UserFileStatus = UserFileStatus.COMPLETED,
    timeout: int = MAX_DELAY,
) -> None:
    """Block until all files reach the target status or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.post(
            f"{API_SERVER_URL}/user/projects/file/statuses",
            json={"file_ids": user_file_ids},
            headers=user.headers,
        )
        response.raise_for_status()
        statuses = response.json()
        if all(f["status"] == target_status.value for f in statuses):
            return
        time.sleep(FILE_PROCESSING_POLL_INTERVAL)
    raise TimeoutError(
        f"Files {user_file_ids} did not reach {target_status.value} "
        f"within {timeout}s"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_persona_with_files_chat_no_error(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """Upload files, attach them to a persona, wait for processing,
    then send a chat message.  Verify no error is returned."""

    # Upload files (creates UserFile records)
    text_file = create_test_text_file(
        "The secret project codename is NIGHTINGALE. "
        "It was started in 2024 by the Advanced Research division."
    )
    file_descriptors, error = FileManager.upload_files(
        files=[("nightingale_brief.txt", text_file)],
        user_performing_action=admin_user,
    )
    assert not error, f"File upload failed: {error}"
    assert len(file_descriptors) == 1

    user_file_id = file_descriptors[0]["user_file_id"]
    assert user_file_id is not None

    # Wait for file processing
    _poll_file_statuses([user_file_id], admin_user, timeout=120)

    # Create persona with the file attached
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Nightingale Agent",
        description="Agent with secret file",
        system_prompt="You are a helpful assistant with access to uploaded files.",
        user_file_ids=[user_file_id],
    )

    # Verify persona has the file
    persona_snapshots = PersonaManager.get_one(persona.id, admin_user)
    assert len(persona_snapshots) == 1
    assert user_file_id in persona_snapshots[0].user_file_ids

    # Chat with the persona
    chat_session = ChatSessionManager.create(
        persona_id=persona.id,
        description="Test persona file context",
        user_performing_action=admin_user,
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the secret project codename?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Chat should succeed, got error: {response.error}"
    assert len(response.full_message) > 0, "Response should not be empty"


def test_persona_without_files_still_works(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """A persona with no attached files should still chat normally."""
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Blank Agent",
        description="No files attached",
        system_prompt="You are a helpful assistant.",
    )

    chat_session = ChatSessionManager.create(
        persona_id=persona.id,
        description="Test blank persona",
        user_performing_action=admin_user,
    )
    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="Hello, how are you?",
        user_performing_action=admin_user,
    )

    assert response.error is None
    assert len(response.full_message) > 0


def test_persona_files_override_project_files(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """When a custom persona (with its own files) is used inside a project,
    the persona's files take precedence — the project's files are invisible.

    We verify this by putting different content in project vs persona files
    and checking which content the model responds with."""

    # Upload persona file
    persona_file = create_test_text_file("The persona's secret word is ALBATROSS.")
    persona_fds, err1 = FileManager.upload_files(
        files=[("persona_secret.txt", persona_file)],
        user_performing_action=admin_user,
    )
    assert not err1
    persona_user_file_id = persona_fds[0]["user_file_id"]
    assert persona_user_file_id is not None
    # Create a project and upload project files
    project = ProjectManager.create(
        name="Precedence Test Project",
        user_performing_action=admin_user,
    )
    project_files = [
        ("project_secret.txt", b"The project's secret word is FLAMINGO."),
    ]
    project_upload_result = ProjectManager.upload_files(
        project_id=project.id,
        files=project_files,
        user_performing_action=admin_user,
    )
    assert len(project_upload_result.user_files) == 1
    project_user_file_id = str(project_upload_result.user_files[0].id)

    # Wait for both persona and project file processing
    _poll_file_statuses([persona_user_file_id], admin_user, timeout=120)
    _poll_file_statuses([project_user_file_id], admin_user, timeout=120)

    # Create persona with persona file
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="Override Agent",
        description="Persona with its own files",
        system_prompt="You are a helpful assistant. Answer using the files.",
        user_file_ids=[persona_user_file_id],
    )

    # Create chat session inside the project but using the custom persona
    chat_session = ChatSessionManager.create(
        persona_id=persona.id,
        project_id=project.id,
        user_performing_action=admin_user,
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the secret word?",
        user_performing_action=admin_user,
    )

    assert response.error is None, f"Chat should succeed, got error: {response.error}"
    # The persona's file should be what the model sees, not the project's
    message_lower = response.full_message.lower()
    assert "albatross" in message_lower, (
        "Response should reference the persona file's secret word (ALBATROSS), "
        f"but got: {response.full_message}"
    )


def test_default_persona_in_project_uses_project_files(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """When the default persona (id=0) is used inside a project,
    the project's files should be used for context."""
    project = ProjectManager.create(
        name="Default Persona Project",
        user_performing_action=admin_user,
    )
    project_files = [
        ("project_info.txt", b"The project mascot is a PANGOLIN."),
    ]
    upload_result = ProjectManager.upload_files(
        project_id=project.id,
        files=project_files,
        user_performing_action=admin_user,
    )
    assert len(upload_result.user_files) == 1

    # Wait for project file processing
    project_file_id = str(upload_result.user_files[0].id)
    _poll_file_statuses([project_file_id], admin_user, timeout=120)

    # Create chat session inside project using default persona (id=0)
    chat_session = ChatSessionManager.create(
        persona_id=0,
        project_id=project.id,
        user_performing_action=admin_user,
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the project mascot?",
        user_performing_action=admin_user,
    )

    assert response.error is None
    assert "pangolin" in response.full_message.lower(), (
        "Response should reference the project file content (PANGOLIN), "
        f"but got: {response.full_message}"
    )


def test_custom_persona_no_files_in_project_ignores_project(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """A custom persona with NO files, used inside a project with files,
    should NOT see the project's files.  The project is purely organizational.

    We verify by asking about content only in the project file and checking
    the model does NOT reference it."""

    project = ProjectManager.create(
        name="Ignored Project",
        user_performing_action=admin_user,
    )
    project_upload_result = ProjectManager.upload_files(
        project_id=project.id,
        files=[("project_only.txt", b"The project secret is CAPYBARA.")],
        user_performing_action=admin_user,
    )
    assert len(project_upload_result.user_files) == 1
    project_user_file_id = str(project_upload_result.user_files[0].id)

    # Wait for project file processing
    _poll_file_statuses([project_user_file_id], admin_user, timeout=120)

    # Custom persona with no files
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="No Files Agent",
        description="No files, project is irrelevant",
        system_prompt=(
            "You are a helpful assistant. If you do not have information "
            "to answer a question, say 'I do not have that information.'"
        ),
    )

    chat_session = ChatSessionManager.create(
        persona_id=persona.id,
        project_id=project.id,
        user_performing_action=admin_user,
    )

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is the project secret?",
        user_performing_action=admin_user,
    )

    assert response.error is None
    assert len(response.full_message) > 0
    assert "capybara" not in response.full_message.lower(), (
        "Response should NOT reference the project file content (CAPYBARA) "
        "because the custom persona has no files and should not inherit "
        f"project files, but got: {response.full_message}"
    )
