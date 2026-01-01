"""
Integration test for image generation heartbeat streaming through the /send-message API.
This test verifies that heartbeat packets are properly streamed through the complete API flow.
"""

import time

import pytest

from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.tools.tool_implementations.images.image_generation_tool import (
    HEARTBEAT_INTERVAL,
)
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestImageGenerationConfig
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ToolName

ART_PERSONA_ID = -3


def test_image_generation_streaming(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,
    image_generation_config: DATestImageGenerationConfig,
) -> None:
    """
    Test image generation to verify:
    1. The image generation tool is invoked successfully
    2. Heartbeat packets are streamed during generation
    3. The response contains the generated image information

    This test uses the actual API without any mocking.
    """
    # Create a chat session with this persona
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    # Send a message that should trigger image generation
    # Use explicit instructions to ensure the image generation tool is used
    message = (
        "Please generate an image of a beautiful sunset over the ocean. "
        "Use the image generation tool to create this image."
    )

    start_time = time.monotonic()
    analyzed_response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=message,
        user_performing_action=basic_user,
    )
    total_time = time.monotonic() - start_time

    assert analyzed_response.error is None, "Chat response should not have an error"

    # 1. Check if image generation tool was used
    image_gen_used = any(
        tool.tool_name == ToolName.IMAGE_GENERATION
        for tool in analyzed_response.used_tools
    )
    assert image_gen_used

    # Verify we received heartbeat packets during image generation
    # Image generation typically takes a few seconds and sends heartbeats
    # every HEARTBEAT_INTERVAL seconds
    expected_heartbeat_packets = max(1, int(total_time / HEARTBEAT_INTERVAL) - 1)
    assert len(analyzed_response.heartbeat_packets) >= expected_heartbeat_packets, (
        f"Expected at least {expected_heartbeat_packets} heartbeats for {total_time:.2f}s execution, "
        f"but got {len(analyzed_response.heartbeat_packets)}"
    )

    # Verify the heartbeat packets have the expected structure
    for packet in analyzed_response.heartbeat_packets:
        assert "obj" in packet, "Heartbeat packet should have 'obj' field"
        assert (
            packet["obj"].get("type") == StreamingType.IMAGE_GENERATION_HEARTBEAT.value
        ), (
            f"Expected heartbeat type to be {StreamingType.IMAGE_GENERATION_HEARTBEAT.value}, "
            f"got {packet['obj'].get('type')}"
        )
    # 4. Verify image generation tool delta packets with actual image data
    image_tool_results = [
        tool
        for tool in analyzed_response.used_tools
        if tool.tool_name == ToolName.IMAGE_GENERATION
    ]
    assert len(image_tool_results) > 0, "Should have image generation tool results"

    image_tool = image_tool_results[0]
    assert len(image_tool.images) > 0, "Should have generated at least one image"


if __name__ == "__main__":
    # Run with: python -m dotenv -f .vscode/.env run --
    # python -m pytest tests/integration/tests/tools/test_image_generation_heartbeat.py -v -s
    pytest.main([__file__, "-v", "-s"])
