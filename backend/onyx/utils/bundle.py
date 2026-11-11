"""Size metadata for resource bundles with caller-owned expansion limits."""

import io
import zipfile

from onyx.file_store.models import BundleLimits, BundleMetadata, FileSizeLimitExceeded


def compute_bundle_metadata(
    bundle_bytes: bytes, *, limits: BundleLimits | None = None
) -> BundleMetadata:
    total = 0
    count = 0
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        for info in sorted(archive.infolist(), key=lambda entry: entry.filename):
            if info.is_dir():
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
