import base64
from io import BytesIO

from PIL import Image

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.llm.interfaces import LLM
from onyx.llm.utils import message_to_string
from onyx.utils.logger import setup_logger


logger = setup_logger()


def summarize_image_pipeline(
    llm: LLM,
    image_data: bytes,
    query: str | None = None,
    system_prompt: str | None = None,
) -> str | None:
    """Pipeline to generate a summary of an image.
    Resizes images if it is bigger than 20MB. Encodes image as a base64 string.
    And finally uses the Default LLM to generate a textual summary of the image."""
    # resize image if it's bigger than 20MB
    image_data = _resize_image_if_needed(image_data)

    # encode image (base64)
    encoded_image = _encode_image(image_data)

    summary = _summarize_image(
        encoded_image,
        llm,
        query,
        system_prompt,
    )

    return summary


def _summarize_image(
    encoded_image: str,
    llm: LLM,
    query: str | None = None,
    system_prompt: str | None = None,
) -> str | None:
    """Use default LLM (if it is multimodal) to generate a summary of an image."""

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": query},
                {"type": "image_url", "image_url": {"url": encoded_image}},
            ],
        },
    ]

    try:
        model_output = message_to_string(llm.invoke(messages))

        return model_output

    except Exception as e:
        if CONTINUE_ON_CONNECTOR_FAILURE:
            # Summary of this image will be empty
            # prevents and infinity retry-loop of the indexing if single summaries fail
            # for example because content filters got triggert...
            logger.warning(f"Summarization failed with error: {e}.")
            return None
        else:
            raise ValueError(f"Summarization failed. Messages: {messages}") from e


def _encode_image(image_data: bytes) -> str:
    """Getting the base64 string."""
    base64_encoded_data = base64.b64encode(image_data).decode("utf-8")

    return f"data:image/jpeg;base64,{base64_encoded_data}"


def _resize_image_if_needed(image_data: bytes, max_size_mb: int = 20) -> bytes:
    """Resize image if it's larger than the specified max size in MB."""
    max_size_bytes = max_size_mb * 1024 * 1024

    if len(image_data) > max_size_bytes:
        with Image.open(BytesIO(image_data)) as img:
            logger.info("resizing image...")

            # Reduce dimensions for better size reduction
            img.thumbnail((800, 800), Image.Resampling.LANCZOS)
            output = BytesIO()

            # Save with lower quality for compression
            img.save(output, format="JPEG", quality=85)
            resized_data = output.getvalue()

            return resized_data

    return image_data
