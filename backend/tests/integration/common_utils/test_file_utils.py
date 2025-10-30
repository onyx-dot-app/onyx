import io

from PIL import Image


def create_test_image(
    width: int = 1,
    height: int = 1,
    color: str = "white",
    format: str = "PNG",
) -> io.BytesIO:
    """Create a test image file in memory for file attachment testing.

    Args:
        width: Width of the image in pixels. Defaults to 1.
        height: Height of the image in pixels. Defaults to 1.
        color: Color of the image. Defaults to "white".
        format: Image format (PNG, JPEG, etc.). Defaults to "PNG".

    Returns:
        A BytesIO object containing the image data, positioned at the start.
    """
    image = Image.new("RGB", (width, height), color=color)
    image_file = io.BytesIO()
    image.save(image_file, format=format)
    image_file.seek(0)
    return image_file


def create_test_text_file(content: str | bytes) -> io.BytesIO:
    """Create a test text file in memory for file attachment testing.

    Args:
        content: The text content of the file. Can be string or bytes.

    Returns:
        A BytesIO object containing the text data, positioned at the start.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    text_file = io.BytesIO(content)
    text_file.seek(0)
    return text_file
