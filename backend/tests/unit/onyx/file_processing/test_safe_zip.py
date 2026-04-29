import io
import zipfile

from onyx.file_processing.safe_zip import read_zip_entry_bounded


def _make_zip(entries: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


def test_read_zip_entry_bounded_returns_bytes_within_budget() -> None:
    payload = b"\0" * 4096
    zf = _make_zip({"payload.bin": payload})

    result = read_zip_entry_bounded(zf, "payload.bin", max_bytes=4096)

    assert result == payload


def test_read_zip_entry_bounded_returns_none_on_overflow() -> None:
    """An entry whose actually-decompressed size exceeds max_bytes returns
    None — the caller decides whether to abort or skip. Importantly, this
    holds even when the zip header's declared file_size would pass."""
    payload = b"\0" * 4096
    zf = _make_zip({"payload.bin": payload})

    result = read_zip_entry_bounded(zf, "payload.bin", max_bytes=1024)

    assert result is None


def test_read_zip_entry_bounded_accepts_zipinfo() -> None:
    payload = b"hello"
    zf = _make_zip({"file.txt": payload})

    info = zf.getinfo("file.txt")
    result = read_zip_entry_bounded(zf, info, max_bytes=10)

    assert result == payload
