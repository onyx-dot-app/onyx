import os

import pytest

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


@pytest.fixture
def dalle3_tool() -> ImageGenerationTool:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    return ImageGenerationTool(
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        num_imgs=1,
        output_format=ImageFormat.URL,
    )


@pytest.fixture
def gpt_image_tool() -> ImageGenerationTool:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    return ImageGenerationTool(
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="gpt-image-1",
        output_format=ImageFormat.BASE64,
        num_imgs=1,
    )


def test_dalle3_generates_image_url_successfully(
    dalle3_tool: ImageGenerationTool,
) -> None:
    # Run the tool with a simple prompt
    results = list(dalle3_tool.run(prompt="A simple red circle"))

    # Verify we get a response
    assert len(results) == 1
    tool_response = results[0]

    # Check response structure
    assert tool_response.id == IMAGE_GENERATION_RESPONSE_ID
    assert isinstance(tool_response.response, list)
    assert len(tool_response.response) == 1

    # Check ImageGenerationResponse content
    image_response = tool_response.response[0]
    assert isinstance(image_response, ImageGenerationResponse)
    assert image_response.revised_prompt is not None
    assert len(image_response.revised_prompt) > 0
    assert image_response.url is not None
    assert image_response.url.startswith("https://")
    assert image_response.image_data is None


def test_dalle3_with_base64_format() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    # Create tool with base64 format
    tool = ImageGenerationTool(
        api_key=api_key,
        api_base=None,
        api_version=None,
        model="dall-e-3",
        output_format=ImageFormat.BASE64,
        num_imgs=1,
    )

    # Run the tool
    results = list(tool.run(prompt="A simple blue square", shape="square"))

    # Verify response
    assert len(results) == 1
    image_response = results[0].response[0]
    assert image_response.url is None
    assert image_response.image_data is not None
    assert len(image_response.image_data) > 0


def test_gpt_image_1_generates_base64_successfully(
    gpt_image_tool: ImageGenerationTool,
) -> None:
    # Run the tool with a simple prompt
    results = list(gpt_image_tool.run(prompt="A simple red circle"))

    # Verify we get a response
    assert len(results) == 1
    tool_response = results[0]

    # Check response structure
    assert tool_response.id == IMAGE_GENERATION_RESPONSE_ID
    assert isinstance(tool_response.response, list)
    assert len(tool_response.response) == 1

    # Check ImageGenerationResponse content
    image_response = tool_response.response[0]
    assert isinstance(image_response, ImageGenerationResponse)
    assert image_response.revised_prompt is not None
    assert len(image_response.revised_prompt) > 0
    assert image_response.url is None
    assert image_response.image_data is not None
    assert len(image_response.image_data) > 0


def test_gpt_image_1_with_url_format_fails() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY environment variable not set")

    # This should fail during tool creation since gpt-image-1 doesn't support URL format
    with pytest.raises(ValueError, match="gpt-image-1 does not support URL format"):
        ImageGenerationTool(
            api_key=api_key,
            api_base=None,
            api_version=None,
            model="gpt-image-1",
            output_format=ImageFormat.URL,
            num_imgs=1,
        )
