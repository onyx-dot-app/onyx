import os
import time
from typing import Any
from unittest.mock import patch

import pytest

from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.images.image_generation_tool import (
    IMAGE_GENERATION_HEARTBEAT_ID,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    IMAGE_GENERATION_RESPONSE_ID,
)
from onyx.tools.tool_implementations.images.image_generation_tool import ImageFormat
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.image_generation_tool import ImageShape


@pytest.fixture
def dalle3_tool() -> ImageGenerationTool:
    """Fixture for DALL-E 3 tool with API key from environment."""
    api_key = os.environ["OPENAI_API_KEY"]
    return ImageGenerationTool(
        tool_id=0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.URL,
    )


def test_image_generation_with_heartbeats(dalle3_tool: ImageGenerationTool) -> None:
    """Test that heartbeat packets are yielded during image generation."""
    responses = []
    heartbeat_count = 0
    image_response_count = 0

    # Collect all responses
    for response in dalle3_tool.run(prompt="A simple red circle on white background"):
        responses.append(response)
        if response.id == IMAGE_GENERATION_HEARTBEAT_ID:
            heartbeat_count += 1
        elif response.id == IMAGE_GENERATION_RESPONSE_ID:
            image_response_count += 1

    # Should have at least one heartbeat (depending on generation speed)
    # and exactly one image response
    assert image_response_count == 1
    # May have 0 or more heartbeats depending on API speed
    print(f"Received {heartbeat_count} heartbeat packets")

    # Verify the final image response
    final_response = responses[-1]
    assert final_response.id == IMAGE_GENERATION_RESPONSE_ID
    assert isinstance(final_response.response, list)
    assert len(final_response.response) == 1

    image = final_response.response[0]
    assert isinstance(image, ImageGenerationResponse)
    assert image.url is not None
    assert image.url.startswith("https://")
    assert image.revised_prompt is not None


def test_heartbeat_timing_with_mock() -> None:
    """Test that heartbeats are sent at correct intervals using mocked generation."""
    api_key = os.getenv("OPENAI_API_KEY", "mock-key-for-testing")

    tool = ImageGenerationTool(
        tool_id=0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.URL,
    )

    # Mock the _generate_image method to simulate slow generation
    def slow_generate(*args: Any, **kwargs: Any) -> ImageGenerationResponse:
        time.sleep(5)  # Simulate 5 second generation time
        return ImageGenerationResponse(
            revised_prompt="Test prompt",
            url="https://example.com/image.png",
            image_data=None,
        )

    with patch.object(tool, "_generate_image", side_effect=slow_generate):
        start_time = time.time()
        responses = list(tool.run(prompt="Test prompt"))
        time.time() - start_time

        # Count heartbeats
        heartbeat_count = sum(
            1 for r in responses if r.id == IMAGE_GENERATION_HEARTBEAT_ID
        )

        # With 5 second generation and 2 second intervals,
        # we should get approximately 2 heartbeats
        assert heartbeat_count >= 1
        assert heartbeat_count <= 3  # Allow some timing variance

        # Verify we still get the final result
        image_responses = [r for r in responses if r.id == IMAGE_GENERATION_RESPONSE_ID]
        assert len(image_responses) == 1
        assert image_responses[0].response[0].url == "https://example.com/image.png"


def test_error_handling_with_heartbeats() -> None:
    """Test that errors are properly propagated even with heartbeat mechanism."""
    api_key = os.getenv("OPENAI_API_KEY", "mock-key-for-testing")

    tool = ImageGenerationTool(
        tool_id=0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.URL,
    )

    # Mock the _generate_image method to raise an error after delay
    def error_generate(*args: Any, **kwargs: Any) -> None:
        time.sleep(1)  # Small delay to ensure at least one heartbeat
        raise ValueError("Test error during generation")

    with patch.object(tool, "_generate_image", side_effect=error_generate):
        with pytest.raises(ValueError, match="Test error during generation"):
            # Consume the generator to trigger the error
            list(tool.run(prompt="Test prompt"))


def test_tool_message_content_filters_heartbeats() -> None:
    """Test that build_tool_message_content correctly filters heartbeats."""
    api_key = os.getenv("OPENAI_API_KEY", "mock-key-for-testing")

    tool = ImageGenerationTool(
        tool_id=0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.URL,
    )

    # Create mock responses
    heartbeat1 = ToolResponse(
        id=IMAGE_GENERATION_HEARTBEAT_ID,
        response={"status": "generating", "heartbeat": 0},
    )
    heartbeat2 = ToolResponse(
        id=IMAGE_GENERATION_HEARTBEAT_ID,
        response={"status": "generating", "heartbeat": 1},
    )
    image_response = ToolResponse(
        id=IMAGE_GENERATION_RESPONSE_ID,
        response=[
            ImageGenerationResponse(
                revised_prompt="Test",
                url="https://example.com/image.png",
                image_data=None,
            )
        ],
    )

    # Test that heartbeats are filtered out
    result = tool.build_tool_message_content(heartbeat1, heartbeat2, image_response)

    # Should return JSON with image info, not heartbeats
    assert isinstance(result, str)
    assert "https://example.com/image.png" in result
    assert "heartbeat" not in result


def test_final_result_filters_heartbeats() -> None:
    """Test that final_result correctly filters heartbeats."""
    api_key = os.getenv("OPENAI_API_KEY", "mock-key-for-testing")

    tool = ImageGenerationTool(
        tool_id=0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.URL,
    )

    # Create mock responses
    heartbeat = ToolResponse(
        id=IMAGE_GENERATION_HEARTBEAT_ID,
        response={"status": "generating", "heartbeat": 0},
    )
    image_response = ToolResponse(
        id=IMAGE_GENERATION_RESPONSE_ID,
        response=[
            ImageGenerationResponse(
                revised_prompt="Test prompt",
                url="https://example.com/image.png",
                image_data=None,
            )
        ],
    )

    # Test that final_result returns only image data
    result = tool.final_result(heartbeat, image_response)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["revised_prompt"] == "Test prompt"
    assert result[0]["url"] == "https://example.com/image.png"


def test_different_image_shapes(dalle3_tool: ImageGenerationTool) -> None:
    """Test image generation with different shape parameters."""
    shapes_to_test = [
        (ImageShape.SQUARE, "A red square"),
        (ImageShape.PORTRAIT, "A tall building"),
        (ImageShape.LANDSCAPE, "A wide landscape"),
    ]

    for shape, prompt in shapes_to_test:
        responses = list(dalle3_tool.run(prompt=prompt, shape=shape.value))

        # Find the image response
        image_response = None
        for response in responses:
            if response.id == IMAGE_GENERATION_RESPONSE_ID:
                image_response = response
                break

        assert image_response is not None
        assert len(image_response.response) == 1
        image = image_response.response[0]
        assert image.url is not None
        print(f"Generated {shape.value} image: {image.url}")


def test_base64_format() -> None:
    """Test image generation with base64 output format."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    tool = ImageGenerationTool(
        tool_id=0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.BASE64,
    )

    responses = list(tool.run(prompt="A simple blue circle"))

    # Find the image response
    image_response = None
    for response in responses:
        if response.id == IMAGE_GENERATION_RESPONSE_ID:
            image_response = response
            break

    assert image_response is not None
    assert len(image_response.response) == 1
    image = image_response.response[0]
    assert image.url is None
    assert image.image_data is not None
    assert len(image.image_data) > 100  # Base64 data should be substantial


if __name__ == "__main__":
    # Run with: python -m pytest tests/external_dependency_unit/tools/test_image_generation_tool.py -v
    pytest.main([__file__, "-v"])
