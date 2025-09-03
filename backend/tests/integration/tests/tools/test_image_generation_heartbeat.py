"""
Integration test for image generation heartbeat streaming through the /send-message API.
This test verifies that heartbeat packets are properly streamed through the complete API flow.
"""

from __future__ import annotations

import time

import pytest

from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.test_models import DATestUser


def test_image_generation_with_mocked_heartbeat_api(
    basic_user: DATestUser,
) -> None:
    """
    Test with mocked image generation to verify heartbeat propagation.
    """
    from unittest.mock import patch
    from onyx.tools.tool_implementations.images.image_generation_tool import (
        ImageGenerationTool,
        ImageGenerationResponse,
    )

    # Mock slow image generation that produces heartbeats
    def mock_slow_generate(self, *args, **kwargs):
        """Mock slow image generation that takes 5 seconds."""
        time.sleep(5)  # Simulate slow generation
        return ImageGenerationResponse(
            revised_prompt="A test image generated slowly",
            url="https://example.com/mock-image.png",
            image_data=None,
        )

    # Skip test if no LLM provider configured
    try:
        from tests.integration.common_utils.managers.llm_provider import (
            LLMProviderManager,
        )

        LLMProviderManager.create(user_performing_action=basic_user)
    except (KeyError, Exception) as e:
        import pytest

        pytest.skip(f"LLM provider not configured: {e}")

    # Set up environment
    chat_session = ChatSessionManager.create(user_performing_action=basic_user)

    # Mock the image generation to be slow
    with patch.object(ImageGenerationTool, "_generate_image", mock_slow_generate):
        # Send message using ChatSessionManager built-in method
        start_time = time.monotonic()
        analyzed_response = ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message="Generate a simple image of a cat",
            user_performing_action=basic_user,
        )

        total_time = time.monotonic() - start_time

        # Verify we got heartbeats (at least 1 heartbeat every 2 seconds)
        expected_heartbeats = max(1, int(total_time / 2) - 1)

        # Log for debugging
        print(f"Total time: {total_time:.2f}s")
        print(f"Heartbeat packets received: {len(analyzed_response.heartbeat_packets)}")
        print(f"Expected at least: {expected_heartbeats}")

        # Check that we received heartbeat packets
        assert len(analyzed_response.heartbeat_packets) >= expected_heartbeats, (
            f"Expected at least {expected_heartbeats} heartbeats for {total_time:.2f}s execution, "
            f"but got {len(analyzed_response.heartbeat_packets)}"
        )


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/tests/streaming_endpoints/test_image_generation_heartbeat_api.py -v -s
    pytest.main([__file__, "-v", "-s"])
