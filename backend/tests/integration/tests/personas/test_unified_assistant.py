"""Integration tests for the unified assistant."""

from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def test_unified_assistant(reset: None, admin_user: DATestUser) -> None:
    """Combined test verifying unified assistant existence, tools, and starter messages."""
    # Fetch all personas
    personas = PersonaManager.get_all(admin_user)

    # Find the unified assistant (ID 0)
    unified_assistant = None
    for persona in personas:
        if persona.id == 0:
            unified_assistant = persona
            break

    # Assert that there are no other assistants (personas) besides the unified assistant
    # (ID 0)
    assert (
        len(personas) == 1
    ), f"Expected only the unified assistant, found {len(personas)} personas"

    # Verify the unified assistant exists
    assert unified_assistant is not None, "Unified assistant (ID 0) not found"

    # Verify basic properties
    assert unified_assistant.name == "Assistant"
    assert (
        "search, web browsing, and image generation"
        in unified_assistant.description.lower()
    )
    assert unified_assistant.is_default_persona is True
    assert unified_assistant.is_visible is True
    assert unified_assistant.num_chunks == 25

    # Verify tools
    tools = unified_assistant.tools
    tool_names = [tool.name for tool in tools]
    assert "SearchTool" in tool_names, "SearchTool not found in unified assistant"
    assert (
        "ImageGenerationTool" in tool_names
    ), "ImageGenerationTool not found in unified assistant"
    assert "WebSearchTool" in tool_names, "WebSearchTool not found in unified assistant"

    # Verify no starter messages
    starter_messages = unified_assistant.starter_messages or []
    assert len(starter_messages) == 0, "Starter messages found"
