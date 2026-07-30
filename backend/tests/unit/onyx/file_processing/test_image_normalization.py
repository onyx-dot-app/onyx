"""Transcoding of vision-API-unsupported image formats (e.g. scanned-PDF TIFFs).

Scanned PDFs embed their pages as 1-bit CCITT TIFFs; vision APIs only accept
PNG/JPEG/GIF/WEBP. These tests pin the normalize-to-PNG behavior end to end:
the helper itself, the summarization encode path, and the wrapper no longer
silently skipping such images.
"""

import io
from unittest.mock import MagicMock

import pytest
from PIL import Image

from onyx.file_processing.image_summarization import (
    _encode_image_for_llm_prompt,
    summarize_image_with_error_handling,
)
from onyx.utils.b64 import get_image_type_from_bytes, normalize_image_for_llm


def _make_image_bytes(mode: str, fmt: str, size: tuple[int, int] = (40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color=1 if mode == "1" else 0).save(buf, format=fmt)
    return buf.getvalue()


def test_bilevel_tiff_is_transcoded_to_png() -> None:
    # Mode "1" TIFF mirrors what scanned-PDF extraction produces.
    tiff_bytes = _make_image_bytes("1", "TIFF")
    with pytest.raises(ValueError):
        get_image_type_from_bytes(tiff_bytes)

    normalized, mime_type = normalize_image_for_llm(tiff_bytes)

    assert mime_type == "image/png"
    assert get_image_type_from_bytes(normalized) == "image/png"
    with Image.open(io.BytesIO(normalized)) as img:
        assert img.format == "PNG"
        assert img.size == (40, 40)


def test_supported_formats_pass_through_unchanged() -> None:
    png_bytes = _make_image_bytes("RGB", "PNG")

    normalized, mime_type = normalize_image_for_llm(png_bytes)

    assert normalized is png_bytes
    assert mime_type == "image/png"


def test_cmyk_tiff_converts_via_rgb() -> None:
    # PNG can't store CMYK — the helper must fall back to an RGB convert.
    cmyk_bytes = _make_image_bytes("CMYK", "TIFF")

    normalized, mime_type = normalize_image_for_llm(cmyk_bytes)

    assert mime_type == "image/png"
    with Image.open(io.BytesIO(normalized)) as img:
        assert img.format == "PNG"
        assert img.mode == "RGB"


def test_undecodable_bytes_raise_value_error() -> None:
    with pytest.raises(ValueError):
        normalize_image_for_llm(b"\x00\x01\x02\x03 not an image")


def test_encode_for_llm_prompt_transcodes_tiff() -> None:
    tiff_bytes = _make_image_bytes("1", "TIFF")

    data_url = _encode_image_for_llm_prompt(tiff_bytes)

    assert data_url.startswith("data:image/png;base64,")


def test_summarize_wrapper_no_longer_skips_tiff() -> None:
    # Before the transcode fix this returned None (silent skip); the LLM must
    # now actually be invoked and its summary returned.
    tiff_bytes = _make_image_bytes("1", "TIFF")
    mock_llm = MagicMock()
    mock_llm.invoke.return_value.choice.message.content = "a scanned page"

    result = summarize_image_with_error_handling(
        llm=mock_llm, image_data=tiff_bytes, context_name="page_1.tiff"
    )

    assert mock_llm.invoke.called
    assert result is not None
