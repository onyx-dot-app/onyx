import base64
from io import BytesIO

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from PIL import Image

from onyx.configs.app_configs import IMAGE_SUMMARIZATION_SYSTEM_PROMPT
from onyx.configs.app_configs import IMAGE_SUMMARIZATION_USER_PROMPT
from onyx.llm.interfaces import LLM
from onyx.llm.utils import message_to_string
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


class UnsupportedImageFormatError(ValueError):
    """Raised when an image uses a MIME type unsupported by the summarization flow."""


def prepare_image_bytes(image_data: bytes) -> str:
    """Prepare image bytes for summarization.
    Resizes image if it's larger than 20MB. Encodes image as a base64 string."""
    image_data = _resize_image_if_needed(image_data)

    # encode image (base64)
    encoded_image = _encode_image_for_llm_prompt(image_data)

    return encoded_image


def summarize_image_pipeline(
    llm: LLM,
    image_data: bytes,
    query: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """Pipeline to generate a summary of an image.
    Resizes images if it is bigger than 20MB. Encodes image as a base64 string.
    And finally uses the Default LLM to generate a textual summary of the image."""
    # resize image if it's bigger than 20MB
    encoded_image = prepare_image_bytes(image_data)

    summary = _summarize_image(
        encoded_image,
        llm,
        query,
        system_prompt,
    )

    return summary


def summarize_image_with_error_handling(
    llm: LLM | None,
    image_data: bytes,
    context_name: str,
    system_prompt: str = IMAGE_SUMMARIZATION_SYSTEM_PROMPT,
    user_prompt_template: str = IMAGE_SUMMARIZATION_USER_PROMPT,
) -> str | None:
    """Wrapper function that handles error cases and configuration consistently.

    Args:
        llm: The LLM with vision capabilities to use for summarization
        image_data: The raw image bytes
        context_name: Name or title of the image for context
        system_prompt: System prompt to use for the LLM
        user_prompt_template: User prompt to use (without title)

    Returns:
        The image summary text, or None if summarization failed or is disabled
    """
    if llm is None:
        return None

    # Prepend the image filename to the user prompt
    user_prompt = (
        f"The image has the file name '{context_name}'.\n{user_prompt_template}"
    )
    try:
        return summarize_image_pipeline(llm, image_data, user_prompt, system_prompt)
    except UnsupportedImageFormatError:
        logger.info(
            "Skipping image summarization due to unsupported MIME type for %s",
            context_name,
        )
        return None


def _summarize_image(
    encoded_image: str,
    llm: LLM,
    query: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """Use default LLM (if it is multimodal) to generate a summary of an image."""

    messages: list[BaseMessage] = []

    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))

    messages.append(
        HumanMessage(
            content=[
                {"type": "text", "text": query},
                {"type": "image_url", "image_url": {"url": encoded_image}},
            ],
        ),
    )

    try:
        return message_to_string(llm.invoke(messages))

    except Exception as e:
        error_msg = f"Summarization failed. Messages: {messages}"
        error_msg = error_msg[:1024]
        raise ValueError(error_msg) from e


def _encode_image_for_llm_prompt(image_data: bytes) -> str:
    """Prepare a data URL with the correct MIME type for the LLM message."""
    try:
        mime_type = get_image_type_from_bytes(image_data)
    except ValueError as exc:
        raise UnsupportedImageFormatError(
            "Unsupported image format for summarization"
        ) from exc

    base64_encoded_data = base64.b64encode(image_data).decode("utf-8")

    return f"data:{mime_type};base64,{base64_encoded_data}"


def _resize_image_if_needed(image_data: bytes, max_size_mb: int = 20) -> bytes:
    """Resize image if it's larger than the specified max size in MB."""
    max_size_bytes = max_size_mb * 1024 * 1024

    if len(image_data) > max_size_bytes:
        with Image.open(BytesIO(image_data)) as img:
            # Reduce dimensions for better size reduction
            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            output = BytesIO()

            # Save with lower quality for compression
            img.save(output, format="JPEG", quality=85)
            resized_data = output.getvalue()

            return resized_data

    return image_data
