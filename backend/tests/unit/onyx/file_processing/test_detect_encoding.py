from io import BytesIO
from unittest import mock

from onyx.file_processing.extract_file_text import detect_encoding


def test_utf8_cyrillic_returns_utf8_without_chardet() -> None:
    """Valid UTF-8 Cyrillic text must be identified as utf-8 without calling chardet."""
    cyrillic = "Привет мир".encode("utf-8")
    with mock.patch("onyx.file_processing.extract_file_text.chardet.detect") as m:
        result = detect_encoding(BytesIO(cyrillic))
    assert result == "utf-8"
    m.assert_not_called()


def test_legacy_encoded_bytes_falls_back_to_chardet() -> None:
    """Bytes that are not valid UTF-8 must fall back to chardet detection."""
    windows1251 = "Привет мир".encode("windows-1251")
    result = detect_encoding(BytesIO(windows1251))
    # chardet should identify this as a Cyrillic legacy encoding, not utf-8
    assert result.lower() != "utf-8"


def test_file_seek_reset_after_call() -> None:
    """detect_encoding must reset the file cursor to 0 so callers can re-read."""
    data = b"hello world"
    f = BytesIO(data)
    detect_encoding(f)
    assert f.tell() == 0
