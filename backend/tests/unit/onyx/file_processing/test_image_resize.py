"""Tests for image resizing logic in image_summarization.py."""

import io
from unittest.mock import patch

from PIL import Image

from onyx.file_processing.image_summarization import _MAX_DIMENSION_PX
from onyx.file_processing.image_summarization import _resize_image_if_needed
from onyx.file_processing.image_summarization import prepare_image_bytes


def _make_png(width: int, height: int) -> bytes:
    """Create a minimal in-memory PNG of the given dimensions."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# -- _resize_image_if_needed ---------------------------------------------------


def test_small_image_unchanged() -> None:
    """An image within both dimension and file-size limits is returned as-is."""
    data = _make_png(800, 600)
    result = _resize_image_if_needed(data)
    assert result is data  # identity check — no copy


def test_oversized_dimensions_resized() -> None:
    """An image exceeding the max dimension is shrunk even if file size is small."""
    data = _make_png(3000, 2000)
    result = _resize_image_if_needed(data)

    with Image.open(io.BytesIO(result)) as img:
        assert max(img.size) <= _MAX_DIMENSION_PX


def test_oversized_file_size_resized() -> None:
    """An image within dimension limits but over file-size limit is resized."""
    # Create a small-dimension image, then pretend it's huge via a tiny max_size_mb
    data = _make_png(800, 600)
    result = _resize_image_if_needed(data, max_size_mb=0)

    # Should have been re-encoded (different bytes)
    assert result != data


def test_custom_max_dimension() -> None:
    """The max_dimension_px parameter is respected."""
    data = _make_png(1200, 900)
    result = _resize_image_if_needed(data, max_dimension_px=1000)

    with Image.open(io.BytesIO(result)) as img:
        assert max(img.size) <= 1000


def test_aspect_ratio_preserved() -> None:
    """Resizing preserves the original aspect ratio."""
    data = _make_png(4000, 2000)  # 2:1
    result = _resize_image_if_needed(data, max_dimension_px=2048)

    with Image.open(io.BytesIO(result)) as img:
        w, h = img.size
        assert w == 2048
        # Allow ±1 px rounding
        assert abs(h - 1024) <= 1


# -- prepare_image_bytes -------------------------------------------------------


@patch("onyx.file_processing.image_summarization.get_image_analysis_max_size_mb")
def test_prepare_image_bytes_uses_workspace_setting(mock_get_max: object) -> None:
    """prepare_image_bytes wires the workspace max-size setting through."""
    from unittest.mock import MagicMock

    mock_get_max = MagicMock(return_value=5)  # type: ignore[assignment]
    with patch(
        "onyx.file_processing.image_summarization.get_image_analysis_max_size_mb",
        mock_get_max,
    ):
        data = _make_png(800, 600)
        result = prepare_image_bytes(data)

    mock_get_max.assert_called_once()
    assert result.startswith("data:image/")
