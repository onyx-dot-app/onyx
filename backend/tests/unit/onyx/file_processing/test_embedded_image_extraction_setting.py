"""The workspace image-extraction setting gates embedded-image extraction for every
image-bearing format, not only PDFs."""

import io
from typing import Any
from unittest.mock import patch

import pytest

from onyx.file_processing.extract_file_text import extract_text_and_images

_MOD = "onyx.file_processing.extract_file_text"


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    "extension, reader, reader_return",
    [
        (".docx", "read_docx_file", ("text", [])),
        (".pdf", "read_pdf_file", ("text", {}, [])),
        (".pptx", "read_pptx_file", ("text", [])),
    ],
)
def test_extract_images_follows_workspace_setting(
    enabled: bool,
    extension: str,
    reader: str,
    reader_return: tuple[Any, ...],
) -> None:
    with (
        patch(f"{_MOD}.get_unstructured_api_key", return_value=None),
        patch(
            f"{_MOD}.get_image_extraction_and_analysis_enabled",
            return_value=enabled,
        ),
        patch(f"{_MOD}.{reader}", return_value=reader_return) as mock_reader,
    ):
        result = extract_text_and_images(io.BytesIO(b"bytes"), f"doc{extension}")

    assert result.text_content == "text"
    mock_reader.assert_called_once()
    assert mock_reader.call_args.kwargs["extract_images"] is enabled
