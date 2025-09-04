"""
Integration test for image generation heartbeat streaming through the /send-message API.
This test verifies that heartbeat packets are properly streamed through the complete API flow.
"""

from __future__ import annotations

import time

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ToolName


def test_image_generation_heartbeat_streaming(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """
    Test image generation to verify heartbeat packets are streamed during generation.
    This test uses the actual API without any mocking.
    """
    # Fetch available tools to get ImageGenerationTool ID
    response = requests.get(
        f"{API_SERVER_URL}/tool",
        headers=basic_user.headers,
    )
    response.raise_for_status()
    tools = response.json()

    # Find ImageGenerationTool ID
    image_gen_tool_id = None
    for tool in tools:
        if tool.get("in_code_tool_id") == "ImageGenerationTool":
            image_gen_tool_id = tool["id"]
            break

    if image_gen_tool_id is None:
        pytest.skip("ImageGenerationTool not found in available tools")

    # Create a persona with image generation tool enabled
    persona = PersonaManager.create(
        name="Image Generation Test Persona",
        description="Persona for testing image generation",
        tool_ids=[image_gen_tool_id],  # Use the actual tool ID
        user_performing_action=basic_user,
    )

    # Create a chat session with this persona
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=basic_user
    )

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

    # Debug output
    print("\n=== DEBUG ===")
    print(f"Response message: {analyzed_response.full_message[:200]}...")
    print(f"Tools used: {[tool.tool_name for tool in analyzed_response.used_tools]}")
    print(f"Image gen used: {image_gen_used}")
    print("=============\n")

    if not image_gen_used:
        # If image generation wasn't triggered, skip the test
        pytest.skip(
            "Image generation tool was not triggered. "
            "This may be due to LLM configuration or prompt not being clear enough."
        )

    # Log for debugging
    print(f"\nTotal time: {total_time:.2f}s")
    print(f"Heartbeat packets received: {len(analyzed_response.heartbeat_packets)}")
    print(f"Tools used: {[tool.tool_name for tool in analyzed_response.used_tools]}")

    # Verify we received heartbeat packets during image generation
    # Image generation typically takes a few seconds and sends heartbeats every 2 seconds
    # We should get at least 1 heartbeat if the process takes more than 2 seconds
    if total_time > 3.0:  # If it took more than 3 seconds
        assert len(analyzed_response.heartbeat_packets) >= 1, (
            f"Expected at least 1 heartbeat for {total_time:.2f}s execution, "
            f"but got {len(analyzed_response.heartbeat_packets)}"
        )

    # Verify the heartbeat packets have the expected structure
    for packet in analyzed_response.heartbeat_packets:
        assert "obj" in packet, "Heartbeat packet should have 'obj' field"
        assert packet["obj"].get("type") == "image_generation_tool_heartbeat", (
            f"Expected heartbeat type to be 'image_generation_tool_heartbeat', "
            f"got {packet['obj'].get('type')}"
        )


def test_image_generation_without_heartbeats(
    basic_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    """
    Test a regular chat message that doesn't trigger image generation.
    This verifies that heartbeat packets are only sent for image generation.
    """
    # Create a chat session
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    # Send a message that should NOT trigger image generation
    message = "What is the capital of France? Just provide a text answer."

    analyzed_response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=message,
        user_performing_action=basic_user,
    )

    # Verify no image generation tool was used
    image_gen_used = any(
        tool.tool_name == ToolName.IMAGE_GENERATION
        for tool in analyzed_response.used_tools
    )
    assert not image_gen_used, "Image generation should not have been triggered"

    # Verify no heartbeat packets for non-image-generation requests
    image_gen_heartbeats = [
        p
        for p in analyzed_response.heartbeat_packets
        if p.get("obj", {}).get("type") == "image_generation_tool_heartbeat"
    ]
    assert len(image_gen_heartbeats) == 0, (
        f"Should not receive image generation heartbeats for regular chat, "
        f"but got {len(image_gen_heartbeats)}"
    )


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/tests/tools/test_image_generation_heartbeat.py -v -s
    pytest.main([__file__, "-v", "-s"])
