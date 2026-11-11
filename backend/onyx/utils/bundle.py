"""Size metadata for resource bundles with caller-owned expansion limits."""

import io
import zipfile
from typing import Final

from onyx.file_store.models import BundleLimits, BundleMetadata, FileSizeLimitExceeded

_IGNORED_BUNDLE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {".DS_Store", "Thumbs.db"}
)


def is_ignored_bundle_path(path: str) -> bool:
    """OS metadata that bundles drop on upload: __MACOSX/, .DS_Store, ._*."""
    parts = path.split("/")
    basename = parts[-1]
    return (
        parts[0] == "__MACOSX"
        or basename in _IGNORED_BUNDLE_FILE_NAMES
        or basename.startswith("._")
    )


def compute_bundle_metadata(
    bundle_bytes: bytes, *, limits: BundleLimits | None = None
) -> BundleMetadata:
    total = 0
    count = 0
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        for info in sorted(archive.infolist(), key=lambda entry: entry.filename):
            if info.is_dir() or is_ignored_bundle_path(info.filename):
                continue
            size = 0
            with archive.open(info) as source:
                while True:
                    read_size = 64 * 1024
                    if limits is not None:
                        read_size = min(
                            read_size,
                            limits.max_file_bytes - size + 1,
                            limits.max_total_bytes - total - size + 1,
                        )
                    chunk = source.read(read_size)
                    if not chunk:
                        break
                    size += len(chunk)
                    if limits is not None and (
                        size > limits.max_file_bytes
                        or total + size > limits.max_total_bytes
                    ):
                        raise FileSizeLimitExceeded(
                            "Expanded bundle exceeds byte limits"
                        )
            total += size
            count += 1
    return BundleMetadata(unpacked_size_bytes=total, file_count=count)
