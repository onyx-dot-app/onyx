import zipfile
from typing import IO, Any

MAX_ZIP_MEMBER_DECOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_TOTAL_DECOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200
_ZIP_RATIO_CHECK_MIN_BYTES = 1024 * 1024


class ZipSizeLimitError(ValueError):
    pass


def assert_zip_within_limits(
    archive: zipfile.ZipFile, *, max_total_bytes: int | None = None
) -> None:
    total_limit: int = (
        MAX_ZIP_TOTAL_DECOMPRESSED_BYTES if max_total_bytes is None else max_total_bytes
    )
    total_size: int = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.file_size > MAX_ZIP_MEMBER_DECOMPRESSED_BYTES:
            raise ZipSizeLimitError("Zip member is too large to extract")
        total_size += info.file_size
        if total_size > total_limit:
            raise ZipSizeLimitError("Zip decompressed size is too large to extract")
        if (
            info.file_size > _ZIP_RATIO_CHECK_MIN_BYTES
            and info.file_size > max(1, info.compress_size) * MAX_ZIP_COMPRESSION_RATIO
        ):
            raise ZipSizeLimitError("Zip member is too compressed to extract")


def assert_zip_container_within_limits(file: IO[Any]) -> None:
    position: int = file.tell()
    try:
        with zipfile.ZipFile(file) as archive:
            assert_zip_within_limits(archive)
    except zipfile.BadZipFile:
        pass
    finally:
        file.seek(position)


def read_zip_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, *, max_bytes: int | None = None
) -> bytes:
    limit: int = MAX_ZIP_MEMBER_DECOMPRESSED_BYTES if max_bytes is None else max_bytes
    if info.file_size > limit:
        raise ZipSizeLimitError("Zip member is too large to extract")
    with archive.open(info) as entry:
        content: bytes = entry.read(max(0, limit) + 1)
    if len(content) > limit:
        raise ZipSizeLimitError("Zip member is too large to extract")
    return content
