"""Logo uploads must agree with the readers that sniff the stored bytes.

An extension check accepted an SVG named `.png` and stored the browser's
Content-Type, so the PDF usage report later sniffed the real type, rejected it,
and silently shipped the bundled mark instead.
"""

from io import BytesIO
from unittest.mock import MagicMock, mock_open, patch

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from ee.onyx.server.enterprise_settings.store import (
    _MAX_LOGO_BYTES,
    sniff_logo_type,
    upload_logo,
)

_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'


def _png(width: int = 8, height: int = 8) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(content: bytes, filename: str) -> MagicMock:
    upload = UploadFile(file=BytesIO(content), filename=filename)
    store = MagicMock()
    with patch(
        "ee.onyx.server.enterprise_settings.store.get_default_file_store",
        return_value=store,
    ):
        upload_logo(file=upload)
    return store


def test_sniffs_the_real_type() -> None:
    assert sniff_logo_type(_png()) == "image/png"
    assert sniff_logo_type(_jpeg()) == "image/jpeg"
    assert sniff_logo_type(_SVG) is None
    assert sniff_logo_type(b"not-an-image") is None
    assert sniff_logo_type(b"") is None


def test_an_svg_disguised_as_png_is_rejected() -> None:
    """The bug: this passed the extension check and failed at render time."""
    with pytest.raises(HTTPException) as caught:
        _upload(_SVG, "logo.png")

    assert caught.value.status_code == 400
    assert "SVG" in caught.value.detail


def test_bytes_that_are_not_an_image_are_rejected() -> None:
    with pytest.raises(HTTPException) as caught:
        _upload(b"still not an image", "logo.jpg")

    assert caught.value.status_code == 400


def test_a_seeded_logo_path_is_validated_too() -> None:
    """`seeding.py` uploads by path, so that branch sniffs bytes as well."""
    store = MagicMock()
    with patch(
        "ee.onyx.server.enterprise_settings.store.get_default_file_store",
        return_value=store,
    ):
        with patch("os.path.isfile", return_value=True):
            with patch("builtins.open", mock_open(read_data=_SVG)):
                assert upload_logo(file="seeded.png") is False
            with patch("builtins.open", mock_open(read_data=_png())):
                assert upload_logo(file="seeded.png") is True


def test_the_stored_type_comes_from_the_bytes_not_the_header() -> None:
    store = _upload(_png(), "logo.png")

    assert store.save_file.call_args.kwargs["file_type"] == "image/png"


def test_an_oversized_logo_is_rejected() -> None:
    with pytest.raises(HTTPException) as caught:
        _upload(b"\x89PNG" + b"\x00" * (_MAX_LOGO_BYTES + 1), "logo.png")

    assert caught.value.status_code == 413


def test_a_real_png_is_accepted() -> None:
    store = _upload(_png(), "logo.png")

    assert store.save_file.called
