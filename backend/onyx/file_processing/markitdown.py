"""Wraps the markitdown library for text extraction from various file types."""
import io
from typing import IO, Any

from markitdown import MarkItDown


def markitdown_to_text(file: IO[Any], file_name: str = "") -> str:
    """Converts a file to markdown text using the markitdown library."""
    file.seek(0)
    content = file.read()
    file.seek(0)
    md = MarkItDown()
    return md.convert(io.BytesIO(content)).text_content
