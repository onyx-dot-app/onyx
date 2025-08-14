"""
Centralized file type validation utilities.
"""

# NOTE(rkuo): Unify this with upload_files_for_chat and extract_file_text

# Standard image MIME types supported by most vision LLMs
IMAGE_MIME_TYPES = [
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
]

# Image types that should be excluded from processing
EXCLUDED_IMAGE_TYPES = [
    "image/bmp",
    "image/tiff",
    "image/gif",
    "image/svg+xml",
    "image/avif",
]

# Text MIME types
TEXT_MIME_TYPE = "text/plain"


def is_valid_image_type(mime_type: str) -> bool:
    """
    Check if mime_type is a valid image type.

    Args:
        mime_type: The MIME type to check

    Returns:
        True if the MIME type is a valid image type, False otherwise
    """
    return (
        bool(mime_type)
        and mime_type.startswith("image/")
        and mime_type not in EXCLUDED_IMAGE_TYPES
    )


def is_supported_by_vision_llm(mime_type: str) -> bool:
    """
    Check if this image type can be processed by vision LLMs.

    Args:
        mime_type: The MIME type to check

    Returns:
        True if the MIME type is supported by vision LLMs, False otherwise
    """
    return mime_type in IMAGE_MIME_TYPES
