import base64
from io import BytesIO
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from litellm import BadRequestError
from openai import RateLimitError
from PIL import Image

from danswer.connectors.confluence.utils import _get_embedded_image_attachments
from danswer.connectors.confluence.utils import _summarize_page_images
from danswer.connectors.confluence.utils import attachment_to_content
from danswer.connectors.confluence.utils import ImageSummarization
from danswer.file_processing.image_summarization import _encode_image
from danswer.file_processing.image_summarization import _resize_image_if_needed
from danswer.file_processing.image_summarization import _summarize_image


# Mocking global variables
CONFLUENCE_IMAGE_SUMMARIZATION_MULTIMODAL_ANSWERING = True
CONFLUENCE_IMAGE_SUMMARIZATION_USER_PROMPT = "Summarize this image"


# Mock LLM class for testing
class MockLLM:
    def invoke(self, messages):
        # Simulate a response object with a 'content' attribute
        class Response:
            def __init__(self, content):
                self.content = content

        # Simulate successful invocation
        return Response("This is a summary of the image.")


# Helper function to create a dummy image
def create_image(size: tuple, color: str, format: str) -> bytes:
    img = Image.new("RGB", size, color)
    output = BytesIO()
    img.save(output, format=format)
    return output.getvalue()


def test_encode_different_image_formats():
    """Tests the base64 encoding of different image formats."""
    formats = ["JPEG", "PNG", "GIF", "EPS"]
    for format in formats:
        image_data = create_image((100, 100), "blue", format)

        expected_output = "data:image/jpeg;base64," + base64.b64encode(
            image_data
        ).decode("utf-8")

        result = _encode_image(image_data)

        assert result == expected_output


def test_resize_image_above_max_size():
    """Test that an image above the max size is resized."""
    image_data = create_image((2000, 2000), "red", "JPEG")  # Large image
    result = _resize_image_if_needed(image_data, max_size_mb=1)

    # Check if the resized image is below the max size
    assert len(result) < (1 * 1024 * 1024)  # Size should be less than 1 MB


def test_summarization_of_images():
    """Test that summarize_image returns a valid summary."""
    encoded_image = "data:image/jpeg;base64,idFuHHIwEEOHVAA..."
    query = "What is in this image?"
    system_prompt = "You are a helpful assistant."
    llm = MockLLM()

    result = _summarize_image(
        encoded_image=encoded_image, query=query, system_prompt=system_prompt, llm=llm
    )
    assert result == "This is a summary of the image."


# Mock response for RateLimitError
class MockResponse:
    def __init__(self):
        self.request = "mock_request"  # Simulate the request attribute
        self.status_code = 429
        self.headers = {"x-request-id": "mock_request_id"}


@pytest.mark.parametrize(
    "exception, expected_output",
    [
        (
            BadRequestError(
                "Content policy violation",
                model="model_name",
                llm_provider="provider_name",
            ),
            "Summarization failed with error: litellm.BadRequestError: Content policy violation.",
        ),
        (
            RateLimitError(
                "Retry limit exceeded", response=MockResponse(), body="body"
            ),
            "Summarization failed with error: Retry limit exceeded.",
        ),
    ],
)
def test_summarize_image_raises_value_error_on_failure(
    mocker, exception, expected_output
):
    llm = MockLLM()

    global CONTINUE_ON_CONNECTOR_FAILURE
    CONTINUE_ON_CONNECTOR_FAILURE = False

    # Set the LLM invoke method to raise the specified exception
    llm.invoke = MagicMock(side_effect=exception)

    # Use pytest.raises to assert that the exception is raised
    with pytest.raises(ValueError) as excinfo:
        _summarize_image("encoded_image_string", llm, "test query", "system prompt")

    # Assert that the exception message matches the expected message
    assert expected_output == str(excinfo.value)


# def test_summarize_image_return_none_on_failure(mocker, exception):
#     llm = MockLLM()

#     global CONTINUE_ON_CONNECTOR_FAILURE
#     CONTINUE_ON_CONNECTOR_FAILURE = True

#     # Mock the invoke method to raise a BadRequestError
#     llm.invoke = MagicMock(side_effect=exception)

#     # Call the summarize_image function
#     result = summarize_image("encoded_image_string", llm, "test query", "system prompt")
#     print(result)
#     # Assert that the result is None
#     assert result is None


@pytest.fixture
def sample_page_image():
    return {
        "id": 123,
        "title": "Sample Image",
        "metadata": {"mediaType": "image/png"},
        "_links": {"download": "dummy-link.mock"},
        "history": {
            "lastUpdated": {"message": "dummy Update"},
        },
        "extensions": {"fileSize": 1},
    }


@pytest.fixture
def sample_page_no_image():
    return {
        "id": 123,
        "title": "Test Image",
        "metadata": {"mediaType": "..."},
        "_links": {"download": "dummy-link.mock"},
        "history": {
            "lastUpdated": {"message": "dummy Update"},
        },
        "extensions": {"fileSize": 1},
    }


@pytest.fixture
def confluence_xml():
    return """
    <document>
        <ac:image>
            <ri:attachment ri:filename="Sample Image" />
        </ac:image>
        <ac:structured-macro ac:name="gliffy">
            <ac:parameter ac:name="imageAttachmentId">123</ac:parameter>
        </ac:structured-macro>
    </document>
    """


def test_get_embedded_image_attachments_with_image(sample_page_image, confluence_xml):
    result = _get_embedded_image_attachments(sample_page_image, confluence_xml)
    print(result)

    assert len(result) == 1
    assert result[0]["id"] == sample_page_image["id"]
    assert result[0]["title"] == sample_page_image["title"]


def test_get_embedded_image_attachment_with_no_image_on_page(
    sample_page_no_image, confluence_xml
):
    result = _get_embedded_image_attachments(sample_page_no_image, confluence_xml)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_summarize_page_images(sample_page_image, confluence_xml):
    USER_PROMPT = "Summarize this image"

    # Mock the Confluence client
    mock_confluence_client = MagicMock()

    # Mock the get method to return valid base64-encoded image data
    image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    mock_confluence_client.get = MagicMock(
        return_value=image_data
    )  # Return base64-encoded string

    # Mock the _get_embedded_image_attachments function
    with patch(
        "danswer.connectors.confluence.utils._get_embedded_image_attachments",
        return_value=[sample_page_image],
    ):
        # Mock the summarize_image function to return a predefined summary
        with patch(
            "danswer.file_processing.image_summarization._summarize_image",
            return_value="This is a summary of the image.",
        ):
            # Mock the image summarization pipeline
            with patch(
                "danswer.file_processing.image_summarization.summarize_image_pipeline",
                return_value="This is a summary of the image.",
            ):
                result = await _summarize_page_images(
                    sample_page_image,
                    mock_confluence_client,
                    USER_PROMPT,
                    confluence_xml,
                    MockLLM(),
                )
                print(result)

    assert len(result) == 1
    assert isinstance(result[0], ImageSummarization)
    assert result[0].title == sample_page_image["title"]
    assert result[0].summary == "This is a summary of the image."
    assert result[0].media_type == sample_page_image["metadata"]["mediaType"]


# def test_attachment_to_content_with_valid_image(sample_page_image, confluence_xml):
#     confluence_client = MagicMock()

#     image_summary = ImageSummarization(
#         url="dummy-link.mock",
#         title="Sample Image",
#         base64_encoded="iVBORw0KGgoAAAANSUhEUgAAAAUA",
#         media_type="image/png",
#         summary="This is an image summary."
#     )

#     with patch('danswer.connectors.confluence.utils._summarize_page_images', return_value=[image_summary]):
#         result = attachment_to_content(confluence_client, sample_page_image, confluence_xml)
#         print(result)

#     assert result == [image_summary]


def test_attachment_to_content_with_no_image(sample_page_no_image, confluence_xml):
    confluence_client = MagicMock()

    with patch("danswer.connectors.confluence.utils._summarize_page_images"):
        result = attachment_to_content(
            confluence_client,
            sample_page_no_image,
            confluence_xml,
            MockLLM(),
        )
        print(result)

    assert result is None
