"""
Integration test for image generation heartbeat streaming through the /send-message API.
This test verifies that heartbeat packets are properly streamed through the complete API flow.
"""

import time

import pytest

from onyx.tools.tool_implementations.images.image_generation_tool import (
    HEARTBEAT_INTERVAL,
)
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ToolName

ART_PERSONA_ID = -3


def test_image_generation_heartbeat_streaming(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """
    Test image generation to verify heartbeat packets are streamed during generation.
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

    # Check if image generation tool was used
    image_gen_used = any(
        tool.tool_name == ToolName.IMAGE_GENERATION
        for tool in analyzed_response.used_tools
    )
    assert image_gen_used

    # Verify we received heartbeat packets during image generation
    # Image generation typically takes a few seconds and sends heartbeats
    # every HEARTBEAT_INTERVAL seconds
    expected_heartbeat_packets = max(1, total_time / HEARTBEAT_INTERVAL - 1)
    assert len(analyzed_response.heartbeat_packets) >= expected_heartbeat_packets, (
        f"Expected at least {expected_heartbeat_packets} heartbeats for {total_time:.2f}s execution, "
        f"but got {len(analyzed_response.heartbeat_packets)}"
    )

    # Verify the heartbeat packets have the expected structure
    for packet in analyzed_response.heartbeat_packets:
        assert "obj" in packet, "Heartbeat packet should have 'obj' field"
        assert packet["obj"].get("type") == "image_generation_tool_heartbeat", (
            f"Expected heartbeat type to be 'image_generation_tool_heartbeat', "
            f"got {packet['obj'].get('type')}"
        )


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/tests/tools/test_image_generation_heartbeat.py -v -s
    pytest.main([__file__, "-v", "-s"])
