from io import BytesIO
from unittest.mock import MagicMock, mock_open, patch

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from ee.onyx.server.enterprise_settings.store import (
    _MAX_LOGO_BYTES,
    sniff_logo_type,
    upload_logo,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'


def _png(width: int = 8, height: int = 8) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(
    content: bytes, filename: str, content_type: str | None = None
) -> MagicMock:
    upload = UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}) if content_type else None,
    )
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
    assert sniff_logo_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) is None


def test_an_svg_named_png_is_rejected() -> None:
    with pytest.raises(OnyxError) as caught:
        _upload(_SVG, "logo.png")

    assert caught.value.status_code == 400


def test_bytes_that_are_not_an_image_are_rejected() -> None:
    with pytest.raises(OnyxError) as caught:
        _upload(b"still not an image", "logo.jpg")

    assert caught.value.status_code == 400


def test_a_truncated_png_is_rejected() -> None:
    with pytest.raises(OnyxError) as caught:
        _upload(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "logo.png")

    assert caught.value.status_code == 400


def test_a_seeded_logo_path_is_validated_too() -> None:
    store = MagicMock()
    with patch(
        "ee.onyx.server.enterprise_settings.store.get_default_file_store",
        return_value=store,
    ):
        with patch("os.path.isfile", return_value=True):
            with patch("builtins.open", mock_open(read_data=b"not an image")):
                assert upload_logo(file="seeded.png") is False
            with patch("builtins.open", mock_open(read_data=_png())):
                assert upload_logo(file="seeded.png") is True


def test_an_oversized_seeded_logo_is_rejected() -> None:
    store = MagicMock()
    with patch(
        "ee.onyx.server.enterprise_settings.store.get_default_file_store",
        return_value=store,
    ):
        with patch("os.path.isfile", return_value=True):
            with patch(
                "builtins.open",
                mock_open(read_data=b"x" * (_MAX_LOGO_BYTES + 1)),
            ):
                assert upload_logo(file="seeded.png") is False

    assert not store.save_file.called


def test_the_stored_type_comes_from_the_bytes_not_the_header() -> None:
    store = _upload(_png(), "logo.png", content_type="image/jpeg")

    assert store.save_file.call_args.kwargs["file_type"] == "image/png"


def test_an_oversized_logo_is_rejected() -> None:
    with pytest.raises(OnyxError) as caught:
        _upload(b"\x89PNG" + b"\x00" * (_MAX_LOGO_BYTES + 1), "logo.png")

    assert caught.value.status_code == 413
    assert caught.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE


def test_a_real_png_is_accepted() -> None:
    store = _upload(_png(), "logo.png")

    assert store.save_file.called
