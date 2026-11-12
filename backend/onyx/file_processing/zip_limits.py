import io
import zipfile
from typing import IO, Any

MAX_ZIP_MEMBER_DECOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_TOTAL_DECOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200
_ZIP_RATIO_CHECK_MIN_BYTES = 1024 * 1024
# zipfile decompresses BZIP2/LZMA input without an output bound, so read(n) cannot cap memory.
_ALLOWED_ZIP_COMPRESSION_TYPES = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
# ZipFile reads up to 64 KiB of comment and the ZIP64 records to find the directory.
_END_RECORD_READ_BYTES = 2 * (64 * 1024 + 22) + 128


class ZipSizeLimitError(ValueError):
    pass


class ZipDirectoryLimitError(ZipSizeLimitError):
    pass


class _ReadBudgetBytesIO(io.BytesIO):
    def __init__(self, data: bytes, budget: int) -> None:
        super().__init__(data)
        self._size = len(data)
        self.budget: int | None = budget

    def read(self, size: int | None = -1, /) -> bytes:
        if self.budget is not None:
            available = max(0, self._size - self.tell())
            wanted = available if size is None or size < 0 else min(size, available)
            if wanted > self.budget:
                raise ZipDirectoryLimitError("Zip file list is too large")
            self.budget -= wanted
        return super().read(size)


def open_zip_within_directory_limit(
    data: bytes, max_directory_bytes: int
) -> zipfile.ZipFile:
    """Open a ZIP whose central directory fits ``max_directory_bytes``.

    ZipFile keeps a ZipInfo for each directory record, so a small archive with
    many entries can use far more memory than its size. ZipFile only parses
    bytes that it reads, so a read budget while it opens bounds that memory.
    """
    file = _ReadBudgetBytesIO(data, max_directory_bytes + _END_RECORD_READ_BYTES)
    archive = zipfile.ZipFile(file)
    file.budget = None
    return archive


def _assert_supported_compression(info: zipfile.ZipInfo) -> None:
    if info.compress_type not in _ALLOWED_ZIP_COMPRESSION_TYPES:
        raise ZipSizeLimitError("Zip member uses an unsupported compression method")


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
        _assert_supported_compression(info)
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


def assert_zip_container_within_limits(
    file: IO[Any], *, max_total_bytes: int | None = None
) -> None:
    position: int = file.tell()
    try:
        with zipfile.ZipFile(file) as archive:
            assert_zip_within_limits(archive, max_total_bytes=max_total_bytes)
    except zipfile.BadZipFile:
        pass
    finally:
        file.seek(position)


def read_zip_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, *, max_bytes: int | None = None
) -> bytes:
    _assert_supported_compression(info)
    limit: int = MAX_ZIP_MEMBER_DECOMPRESSED_BYTES if max_bytes is None else max_bytes
    if info.file_size > limit:
        raise ZipSizeLimitError("Zip member is too large to extract")
    with archive.open(info) as entry:
        content: bytes = entry.read(max(0, limit) + 1)
    if len(content) > limit:
        raise ZipSizeLimitError("Zip member is too large to extract")
    return content
