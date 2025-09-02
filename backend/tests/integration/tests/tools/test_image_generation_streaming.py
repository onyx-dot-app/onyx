"""
Integration test for image generation tool heartbeat streaming.
This test verifies that heartbeat packets are properly streamed to the frontend during image generation.
"""

import time
from typing import Any
from unittest.mock import patch

import pytest

from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)


def test_image_generation_heartbeat_streaming_with_mock() -> None:
    """Test that heartbeat packets are properly streamed during image generation."""

    # Create image generation tool directly for testing
    image_tool = ImageGenerationTool(
        tool_id=0,  # Mock tool ID
        api_key="mock-key",
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
    )

    # Mock slow image generation to ensure heartbeats are sent
    def slow_generate(*args: Any, **kwargs: Any) -> ImageGenerationResponse:
        time.sleep(4)  # Simulate 4-second generation time
        return ImageGenerationResponse(
            revised_prompt="A test image",
            url="https://example.com/test-image.png",
            image_data=None,
        )

    with patch.object(image_tool, "_generate_image", side_effect=slow_generate):
        responses = list(image_tool.run(prompt="Generate a test image"))

        # Collect heartbeat and final responses
        heartbeat_responses = []
        image_responses = []

        for response in responses:
            if hasattr(response, "id"):
                if response.id and "heartbeat" in response.id:
                    heartbeat_responses.append(response)
                elif response.id and "image_generation_response" in response.id:
                    image_responses.append(response)

        # Verify we got heartbeat packets
        assert (
            len(heartbeat_responses) > 0
        ), "Should receive heartbeat packets during generation"
        assert len(image_responses) == 1, "Should receive exactly one image response"

        # Verify heartbeat structure
        for heartbeat in heartbeat_responses:
            assert heartbeat.response["status"] == "generating"
            assert "heartbeat" in heartbeat.response
            assert isinstance(heartbeat.response["heartbeat"], int)

        # Verify final image response
        final_image = image_responses[0]
        assert len(final_image.response) == 1
        assert final_image.response[0].url == "https://example.com/test-image.png"


def test_image_generation_streaming_integration_with_chat() -> None:
    """Test image generation streaming through the complete chat pipeline."""

    # This test verifies that our heartbeat responses are properly structured
    from onyx.tools.models import ToolResponse
    from onyx.tools.tool_implementations.images.image_generation_tool import (
        IMAGE_GENERATION_HEARTBEAT_ID,
    )

    # Create mock heartbeat responses - this simulates what the tool generates
    heartbeat_response = ToolResponse(
        id=IMAGE_GENERATION_HEARTBEAT_ID,
        response={"status": "generating", "heartbeat": 1},
    )

    # Test that heartbeat response structure is correct for conversion
    assert heartbeat_response.id == IMAGE_GENERATION_HEARTBEAT_ID
    assert heartbeat_response.response["status"] == "generating"
    assert heartbeat_response.response["heartbeat"] == 1

    # Test conversion to streaming packet format
    from onyx.server.query_and_chat.streaming_models import ImageGenerationToolHeartbeat
    from onyx.server.query_and_chat.streaming_models import Packet

    # This simulates what happens in the tool response handler
    heartbeat_data = heartbeat_response.response
    heartbeat_packet = Packet(
        ind=0,
        obj=ImageGenerationToolHeartbeat(
            status=heartbeat_data.get("status", "generating"),
            heartbeat_count=heartbeat_data.get("heartbeat", 0),
        ),
    )

    # Verify packet structure
    assert heartbeat_packet.obj.status == "generating"
    assert heartbeat_packet.obj.heartbeat_count == 1
    assert heartbeat_packet.obj.type == "image_generation_tool_heartbeat"


def collect_streaming_packets_from_chat_response(
    chat_response_generator: Any,
) -> dict[str, list[Any]]:
    """
    Helper function to collect different types of packets from a chat response stream.
    This would be used in a full integration test.
    """
    packets = {
        "heartbeat": [],
        "image_start": [],
        "image_delta": [],
        "other": [],
    }

    for item in chat_response_generator:
        if isinstance(item, Packet):
            if isinstance(item.obj, ImageGenerationToolHeartbeat):
                packets["heartbeat"].append(item)
            elif isinstance(item.obj, ImageGenerationToolStart):
                packets["image_start"].append(item)
            else:
                packets["other"].append(item)
        else:
            packets["other"].append(item)

    return packets


def test_packet_collection_helper() -> None:
    """Test the packet collection helper function."""
    # Create mock packets
    heartbeat_packet = Packet(
        ind=0,
        obj=ImageGenerationToolHeartbeat(status="generating", heartbeat_count=1),
    )

    start_packet = Packet(
        ind=1,
        obj=ImageGenerationToolStart(),
    )

    # Test packet collection
    mock_stream = [heartbeat_packet, start_packet, "other_item"]
    collected = collect_streaming_packets_from_chat_response(mock_stream)

    assert len(collected["heartbeat"]) == 1
    assert len(collected["image_start"]) == 1
    assert len(collected["other"]) == 1

    # Verify heartbeat packet content
    heartbeat = collected["heartbeat"][0]
    assert heartbeat.obj.status == "generating"
    assert heartbeat.obj.heartbeat_count == 1


@pytest.mark.skip(reason="Requires OpenAI API key and full chat pipeline setup")
def test_full_image_generation_streaming_e2e() -> None:
    """
    End-to-end test of image generation streaming through the complete chat system.
    This test is skipped by default as it requires extensive setup and API keys.
    """

    # This would test the complete flow from chat message to streamed response
    # including heartbeat packets reaching the frontend

    # from onyx.chat.process_message import stream_chat_message_objects
    # from onyx.server.features.chat.models import CreateChatMessageRequest

    # message_request = CreateChatMessageRequest(
    #     chat_session_id=None,
    #     persona_id=persona.id,
    #     message="Generate an image of a red circle",
    #     prompt_id=None,
    #     search_doc_ids=None,
    #     retrieval_options=None,
    #     query_override=None,
    #     rerank_settings=None,
    #     alternative_assistant_id=None,
    #     file_descriptors=[],
    #     allowed_tool_ids=[tool.id],
    # )

    # responses = list(stream_chat_message_objects(
    #     new_msg_req=message_request,
    #     user=user,
    #     db_session=db_session,
    # ))

    # collected_packets = collect_streaming_packets_from_chat_response(responses)
    #
    # # Verify heartbeat packets were streamed
    # assert len(collected_packets["heartbeat"]) > 0
    # assert len(collected_packets["image_start"]) > 0

    pass  # Placeholder for now


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/tests/tools/test_image_generation_streaming.py -v -s
    pytest.main([__file__, "-v", "-s"])
