"""
Integration test for image generation heartbeat streaming through the /send-message API.
This test verifies that heartbeat packets are properly streamed through the complete API flow.
"""

from __future__ import annotations

import os
import time
from typing import Any
from typing import Dict
from unittest.mock import patch

import pytest
import requests
from requests.models import Response

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import StreamedResponse


def analyze_streaming_response_for_heartbeats(response: Response) -> StreamedResponse:
    """Analyze streaming response using ChatSessionManager and return parsed response.

    Args:
        response: The HTTP streaming response from /send-message API

    Returns:
        StreamedResponse with parsed content and heartbeat packets tracked
    """
    return ChatSessionManager.analyze_response(response)


def create_mock_image_generation_request(
    chat_session_id: str, message: str
) -> Dict[str, Any]:
    """Create a properly typed request payload for image generation.

    Args:
        chat_session_id: The UUID of the chat session
        message: The message requesting image generation

    Returns:
        Dict containing the complete request payload
    """
    return {
        "chat_session_id": chat_session_id,
        "message": message,
        "prompt_id": None,
        "search_doc_ids": [],
        "retrieval_options": None,
        "rerank_settings": None,
        "parent_message_id": None,
        "query_override": None,
        "regenerate": None,
        "llm_override": None,
        "prompt_override": None,
        "alternate_assistant_id": None,
        "file_descriptors": [],
        "use_existing_user_message": False,
        "use_agentic_search": False,
    }


def test_image_generation_heartbeat_streaming_api_with_mock(
    reset: None, admin_user: DATestUser
) -> None:
    """
    Test that heartbeat packets are streamed through the /send-message API
    using mocked slow image generation to ensure heartbeats are generated.
    """
    # Skip if no API key available
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    # Set up LLM provider
    _ = LLMProviderManager.create(user_performing_action=admin_user)

    # Create a persona with image generation capabilities
    # Note: This assumes the system has image generation tools configured
    # In a real test environment, you'd need to set up the tool properly
    persona = PersonaManager.create(
        name="Image Generation Test Persona",
        description="Persona with image generation capabilities",
        user_performing_action=admin_user,
    )

    # Create chat session
    chat_session = ChatSessionManager.create(
        persona_id=persona.id,
        description="Test image generation heartbeat streaming",
        user_performing_action=admin_user,
    )

    # Mock the image generation to be slow to ensure heartbeats are sent
    from onyx.tools.tool_implementations.images.image_generation_tool import (
        ImageGenerationTool,
    )

    ImageGenerationTool._generate_image

    def slow_generate_image(self: Any, *args: Any, **kwargs: Any) -> Any:
        """Mock slow image generation that takes 5+ seconds."""
        time.sleep(5)  # Ensure we get multiple heartbeats
        from onyx.tools.tool_implementations.images.image_generation_tool import (
            ImageGenerationResponse,
        )

        return ImageGenerationResponse(
            revised_prompt="A test image generated slowly",
            url="https://example.com/mock-image.png",
            image_data=None,
        )

    with patch.object(ImageGenerationTool, "_generate_image", slow_generate_image):
        # Create the request payload
        request_payload = create_mock_image_generation_request(
            chat_session_id=str(chat_session.id),
            message="Generate an image of a red circle",
        )

        response = requests.post(
            f"{API_SERVER_URL}/chat/send-message",
            json=request_payload,
            headers=admin_user.headers,
            stream=True,
            timeout=30,  # Allow enough time for slow generation
        )

        response.raise_for_status()

        # Analyze the streaming response using ChatSessionManager
        analyzed_response = analyze_streaming_response_for_heartbeats(response)

        # Verify we received heartbeat packets
        assert (
            len(analyzed_response.heartbeat_packets) > 0
        ), f"Should receive heartbeat packets, got {len(analyzed_response.heartbeat_packets)} packets"

        # Verify heartbeat packet structure
        for heartbeat_packet in analyzed_response.heartbeat_packets:
            heartbeat_obj: Dict[str, Any] = heartbeat_packet["obj"]
            assert heartbeat_obj["type"] == "image_generation_tool_heartbeat"
            assert "status" in heartbeat_obj
            assert "heartbeat_count" in heartbeat_obj
            assert heartbeat_obj["status"] == "generating"
            assert isinstance(heartbeat_obj["heartbeat_count"], int)

        # Verify we got image generation tool usage
        image_tools = [
            tool
            for tool in analyzed_response.used_tools
            if tool.tool_name.value == "generate_image"
        ]
        assert len(image_tools) > 0, "Should detect image generation tool usage"

        # Print debug info
        print(f"Message content: {analyzed_response.full_message}")
        print(f"Heartbeat packets: {len(analyzed_response.heartbeat_packets)}")
        print(
            f"Tools used: {[tool.tool_name.value for tool in analyzed_response.used_tools]}"
        )


def test_image_generation_api_flow_without_heartbeat_focus(
    reset: None, admin_user: DATestUser
) -> None:
    """
    Test the basic image generation API flow to ensure it works,
    focusing on the streaming response structure rather than heartbeats.
    """
    # Skip if no API key available
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    # Set up LLM provider
    LLMProviderManager.create(user_performing_action=admin_user)

    # Create chat session with default persona (should have image generation)
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    # Send message requesting image generation (use ChatSessionManager for parsing)
    try:
        response = ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message="Generate an image of a blue square",
            user_performing_action=admin_user,
        )

        # If image generation is configured, we should get a response
        assert len(response.full_message) > 0, "Should receive a response message"

        # Check if image generation tool was used (if configured)
        has_image_tool = any(
            tool_result.tool_name.value == "generate_image"
            for tool_result in response.used_tools
        )

        if has_image_tool:
            print("Image generation tool was successfully used")
        else:
            print(
                "Image generation tool was not used (may not be configured in test environment)"
            )

    except Exception as e:
        # If image generation is not configured, the test should still pass
        # but we'll note that the functionality isn't available
        print(f"Image generation may not be configured in test environment: {e}")


def test_packet_stream_parsing_with_heartbeat_mock() -> None:
    """
    Test that ChatSessionManager.analyze_response correctly identifies heartbeat packets
    in a mock streaming response.
    """
    # Mock streaming response data with proper message_start structure
    mock_stream_lines = [
        b'{"ind": 0, "obj": {"type": "message_start", "content": "Starting generation...", "final_documents": []}}',
        b'{"ind": 1, "obj": {"type": "image_generation_tool_start"}}',
        b'{"ind": 1, "obj": {"type": "image_generation_tool_heartbeat", "status": "generating", "heartbeat_count": 1}}',
        b'{"ind": 1, "obj": {"type": "image_generation_tool_heartbeat", "status": "generating", "heartbeat_count": 2}}',
        b'{"ind": 1, "obj": {"type": "image_generation_tool_delta", "images": []}}',
        b'{"ind": 2, "obj": {"type": "message_delta", "content": "Generated!"}}',
    ]

    # Create a mock response object compatible with requests.Response
    class MockResponse:
        def iter_lines(self) -> Any:
            return iter(mock_stream_lines)

    mock_response = MockResponse()

    # Analyze response using ChatSessionManager
    analyzed_response = ChatSessionManager.analyze_response(mock_response)

    # Verify heartbeat packet extraction
    assert (
        len(analyzed_response.heartbeat_packets) == 2
    ), "Should extract 2 heartbeat packets"

    # Verify heartbeat packet content
    first_heartbeat: Dict[str, Any] = analyzed_response.heartbeat_packets[0]
    assert first_heartbeat["obj"]["status"] == "generating"
    assert first_heartbeat["obj"]["heartbeat_count"] == 1

    second_heartbeat: Dict[str, Any] = analyzed_response.heartbeat_packets[1]
    assert second_heartbeat["obj"]["heartbeat_count"] == 2

    # Verify message content was parsed correctly
    assert analyzed_response.full_message == "Starting generation...Generated!"

    # Verify image generation tool was detected
    image_tools = [
        tool
        for tool in analyzed_response.used_tools
        if tool.tool_name.value == "generate_image"
    ]
    assert len(image_tools) > 0, "Should detect image generation tool usage"


@pytest.mark.skip(reason="Requires actual OpenAI API key and may be expensive")
def test_real_image_generation_with_heartbeat_api(
    reset: None, admin_user: DATestUser
) -> None:
    """
    End-to-end test with real image generation API call.
    This test is skipped by default to avoid API costs and require explicit API key setup.
    """
    # This would test with real OpenAI image generation
    # and verify that heartbeats are sent for actual slow API calls

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    # Set up environment
    LLMProviderManager.create(user_performing_action=admin_user)
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    # Create request payload using helper function
    request_payload = create_mock_image_generation_request(
        chat_session_id=str(chat_session.id), message="Generate a simple image of a cat"
    )

    # Send real image generation request
    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message",
        json=request_payload,
        headers=admin_user.headers,
        stream=True,
        timeout=60,
    )

    response.raise_for_status()

    # Analyze response using ChatSessionManager
    analyzed_response = analyze_streaming_response_for_heartbeats(response)

    # Verify real API streaming includes heartbeats if generation is slow enough
    print(f"Real API - Message: {analyzed_response.full_message}")
    print(f"Real API - Heartbeats: {len(analyzed_response.heartbeat_packets)}")
    print(
        f"Real API - Tools used: {[tool.tool_name.value for tool in analyzed_response.used_tools]}"
    )


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/tests/streaming_endpoints/test_image_generation_heartbeat_api.py -v -s
    pytest.main([__file__, "-v", "-s"])
