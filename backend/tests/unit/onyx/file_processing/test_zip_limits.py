import io
import tracemalloc
import zipfile

import pytest

from onyx.file_processing.zip_limits import (
    ZipDirectoryLimitError,
    open_zip_within_directory_limit,
)


def _zip(names: list[str], *, comment: bytes = b"") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
        archive.comment = comment
    return output.getvalue()


def _directory_bytes(data: bytes) -> int:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return sum(46 + len(info.filename) for info in archive.infolist())


def test_refuses_many_entries_before_zipfile_builds_them() -> None:
    data = _zip([str(index) for index in range(200_000)])

    tracemalloc.start()
    try:
        with pytest.raises(ZipDirectoryLimitError):
            open_zip_within_directory_limit(data, 1024 * 1024)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # zipfile alone uses about 100 MiB for this archive.
    assert peak < 1024 * 1024


@pytest.mark.parametrize("comment", [b"", b"c" * 65535], ids=["none", "max"])
def test_opens_directory_within_limit_and_reads_members(comment: bytes) -> None:
    data = _zip([f"refs/{index:05d}.md" for index in range(10_000)], comment=comment)
    limit = _directory_bytes(data)

    with open_zip_within_directory_limit(data, limit) as archive:
        assert len(archive.infolist()) == 10_000
        assert archive.read("refs/09999.md") == b"x"
    with pytest.raises(ZipDirectoryLimitError):
        open_zip_within_directory_limit(data, limit // 4)


def test_member_reads_are_not_limited_after_open() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("large.bin", b"x" * (2 * 1024 * 1024))

    with open_zip_within_directory_limit(output.getvalue(), 1024) as archive:
        assert len(archive.read("large.bin")) == 2 * 1024 * 1024


def test_invalid_zip_still_raises_bad_zip_file() -> None:
    with pytest.raises(zipfile.BadZipFile):
        open_zip_within_directory_limit(b"not a zip", 1024)
