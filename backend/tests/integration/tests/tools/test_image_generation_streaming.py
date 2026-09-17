"""Image generation streams tool results through the chat API."""

from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import (
    DATestImageGenerationConfig,
    DATestLLMProvider,
    DATestUser,
    ToolName,
)

ART_PERSONA_ID = -3


def test_image_generation_streaming(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
    image_generation_config: DATestImageGenerationConfig,  # noqa: ARG001
) -> None:
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    message = "Please generate an image of a beautiful sunset over the ocean. Use the image generation tool to create this image."

    analyzed_response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=message,
        user_performing_action=basic_user,
    )

    assert analyzed_response.error is None, "Chat response should not have an error"

    image_gen_used = any(
        tool.tool_name == ToolName.IMAGE_GENERATION
        for tool in analyzed_response.used_tools
    )
    assert image_gen_used

    for packet in analyzed_response.heartbeat_packets:
        assert packet["obj"]["type"] == "chat_heartbeat"

    image_tool_results = [
        tool
        for tool in analyzed_response.used_tools
        if tool.tool_name == ToolName.IMAGE_GENERATION
    ]
    assert len(image_tool_results) > 0, "Should have image generation tool results"

    image_tool = image_tool_results[0]
    assert len(image_tool.images) > 0, "Should have generated at least one image"
