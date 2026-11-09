"""
Integration test for requesting image generation with a preference through the chat API.
The request asks for an image and prefers the image Action.
"""

import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Tool
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import (
    DATestImageGenerationConfig,
    DATestLLMProvider,
    DATestUser,
    ToolName,
)


def test_preferred_image_action(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    image_generation_config: DATestImageGenerationConfig,  # noqa: ARG001
) -> None:
    with get_session_with_current_tenant() as db_session:
        image_generation_tool = db_session.execute(
            select(Tool).where(Tool.in_code_tool_id == "ImageGenerationTool")
        ).scalar_one_or_none()
        assert image_generation_tool is not None, "ImageGenerationTool must exist"
        image_generation_tool_id = image_generation_tool.id

    # Create a chat session
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    message = "Generate an image of a small blue boat on a calm lake."

    analyzed_response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=message,
        user_performing_action=basic_user,
        preferred_tool_id=image_generation_tool_id,
    )

    assert analyzed_response.error is None, "Chat response should not have an error"

    image_generation_tool_used = any(
        tool.tool_name == ToolName.IMAGE_GENERATION
        for tool in analyzed_response.used_tools
    )
    assert image_generation_tool_used, "The image request should produce an image"


if __name__ == "__main__":
    # Run with: python -m dotenv -f .vscode/.env run --
    # python -m pytest backend/tests/integration/tests/tools/test_preferred_image_action.py -v -s
    pytest.main([__file__, "-v", "-s"])
