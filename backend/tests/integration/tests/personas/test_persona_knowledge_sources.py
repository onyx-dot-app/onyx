"""
Integration tests verifying the knowledge_sources field on MinimalPersonaSnapshot.

The GET /persona endpoint returns MinimalPersonaSnapshot, which includes a
knowledge_sources list derived from the persona's document sets, hierarchy
nodes, attached documents, and user files.  These tests verify that the
field is populated correctly.
"""

import requests

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.file import FileManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_file_utils import create_test_text_file
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


def _get_minimal_persona(
    persona_id: int,
    user: DATestUser,
) -> dict:
    """Fetch personas from the list endpoint and find the one with the given id."""
    response = requests.get(
        f"{API_SERVER_URL}/persona",
        params={"persona_ids": persona_id},
        headers=user.headers,
    )
    response.raise_for_status()
    personas = response.json()
    matches = [p for p in personas if p["id"] == persona_id]
    assert (
        len(matches) == 1
    ), f"Expected 1 persona with id={persona_id}, got {len(matches)}"
    return matches[0]


def test_persona_with_user_files_includes_user_file_source(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """When a persona has user files attached, knowledge_sources includes 'user_file'."""
    text_file = create_test_text_file("test content for knowledge source verification")
    file_descriptors, error = FileManager.upload_files(
        files=[("test_ks.txt", text_file)],
        user_performing_action=admin_user,
    )
    assert not error, f"File upload failed: {error}"

    user_file_id = file_descriptors[0]["user_file_id"] or ""

    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="KS User File Agent",
        description="Agent with user files for knowledge_sources test",
        system_prompt="You are a helpful assistant.",
        user_file_ids=[user_file_id],
    )

    minimal = _get_minimal_persona(persona.id, admin_user)
    assert (
        DocumentSource.USER_FILE.value in minimal["knowledge_sources"]
    ), f"Expected 'user_file' in knowledge_sources, got: {minimal['knowledge_sources']}"


def test_persona_without_user_files_excludes_user_file_source(
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    """When a persona has no user files, knowledge_sources should not contain 'user_file'."""
    persona = PersonaManager.create(
        user_performing_action=admin_user,
        name="KS No Files Agent",
        description="Agent without files for knowledge_sources test",
        system_prompt="You are a helpful assistant.",
    )

    minimal = _get_minimal_persona(persona.id, admin_user)
    assert (
        DocumentSource.USER_FILE.value not in minimal["knowledge_sources"]
    ), f"Unexpected 'user_file' in knowledge_sources: {minimal['knowledge_sources']}"
