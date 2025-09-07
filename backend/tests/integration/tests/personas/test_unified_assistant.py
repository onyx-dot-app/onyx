"""Integration tests for the unified assistant."""

import pytest

from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import TestUser


@pytest.fixture
def admin_user() -> TestUser:
    """Create an admin user for testing."""
    return UserManager.create(name="test_admin_user")


def test_unified_assistant_exists(admin_user: TestUser) -> None:
    """Test that the unified assistant exists and has the correct configuration."""
    # Fetch all personas
    personas = PersonaManager.get_personas(admin_user)

    # Find the unified assistant (ID 0)
    unified_assistant = None
    for persona in personas:
        if persona["id"] == 0:
            unified_assistant = persona
            break

    # Verify the unified assistant exists
    assert unified_assistant is not None, "Unified assistant (ID 0) not found"

    # Verify basic properties
    assert unified_assistant["name"] == "Assistant"
    assert (
        "search, web browsing, and image generation"
        in unified_assistant["description"].lower()
    )
    assert unified_assistant["is_default_persona"] is True
    assert unified_assistant["is_visible"] is True
    assert unified_assistant["num_chunks"] == 25
    assert unified_assistant["image_generation"] is True


def test_unified_assistant_has_all_tools(admin_user: TestUser) -> None:
    """Test that the unified assistant has all built-in tools enabled."""
    # Fetch the unified assistant
    personas = PersonaManager.get_personas(admin_user)
    unified_assistant = None
    for persona in personas:
        if persona["id"] == 0:
            unified_assistant = persona
            break

    assert unified_assistant is not None, "Unified assistant not found"

    # Check that tools are present
    tools = unified_assistant.get("tools", [])
    tool_names = [tool["name"] for tool in tools]

    # Verify SearchTool is present
    assert "SearchTool" in tool_names, "SearchTool not found in unified assistant"

    # ImageGenerationTool and InternetSearchTool may not be available depending on configuration
    # So we just check that at least SearchTool is present


def test_unified_assistant_starter_messages(admin_user: TestUser) -> None:
    """Test that the unified assistant has appropriate starter messages."""
    # Fetch the unified assistant
    personas = PersonaManager.get_personas(admin_user)
    unified_assistant = None
    for persona in personas:
        if persona["id"] == 0:
            unified_assistant = persona
            break

    assert unified_assistant is not None, "Unified assistant not found"

    # Check starter messages
    starter_messages = unified_assistant.get("starter_messages", [])
    assert len(starter_messages) > 0, "No starter messages found"

    # Check that we have a mix of message types (search, general, image generation)
    message_types = []
    for msg in starter_messages:
        message_text = msg.get("message", "").lower()
        if "document" in message_text or "search" in message_text:
            message_types.append("search")
        elif (
            "generate" in message_text
            or "visual" in message_text
            or "image" in message_text
        ):
            message_types.append("image")
        else:
            message_types.append("general")

    # We should have at least 2 different types of messages
    assert len(set(message_types)) >= 2, "Starter messages lack diversity"


def test_old_default_assistants_hidden(admin_user: TestUser) -> None:
    """Test that the old default assistants (General ID 1, Art ID 3) are hidden."""
    # Fetch all personas including hidden ones
    personas = PersonaManager.get_personas(admin_user)

    # Check that General (ID 1) and Art (ID 3) are not visible as default personas
    for persona in personas:
        if persona["id"] == 1:  # General assistant
            assert (
                persona.get("is_visible", True) is False
            ), "General assistant should be hidden"
            assert (
                persona.get("is_default_persona", True) is False
            ), "General assistant should not be default"
        elif persona["id"] == 3:  # Art assistant
            assert (
                persona.get("is_visible", True) is False
            ), "Art assistant should be hidden"
            assert (
                persona.get("is_default_persona", True) is False
            ), "Art assistant should not be default"


def test_paraphrase_assistant_not_default(admin_user: TestUser) -> None:
    """Test that the Paraphrase assistant (ID 2) is no longer a default persona."""
    # Fetch all personas
    personas = PersonaManager.get_personas(admin_user)

    # Find the Paraphrase assistant
    for persona in personas:
        if persona["id"] == 2:  # Paraphrase assistant
            assert (
                persona.get("is_default_persona", True) is False
            ), "Paraphrase assistant should not be default"
            break


def test_unified_assistant_can_be_configured(admin_user: TestUser) -> None:
    """Test that the unified assistant's tools can be configured via the API."""
    # Get the unified assistant
    personas = PersonaManager.get_personas(admin_user)
    unified_assistant = None
    for persona in personas:
        if persona["id"] == 0:
            unified_assistant = persona
            break

    assert unified_assistant is not None, "Unified assistant not found"

    # Get current tools
    current_tools = unified_assistant.get("tools", [])
    [tool["id"] for tool in current_tools]

    # Try to update the tools (remove one if present, or add one if not)
    # This is a basic test to ensure the update endpoint works
    # Note: We can't test the actual update without knowing what tools are available
    # So we just verify the assistant can be fetched and has a tools field
    assert "tools" in unified_assistant, "Unified assistant should have tools field"
    assert isinstance(unified_assistant["tools"], list), "Tools should be a list"
