"""Content metadata for resource bundles with caller-owned expansion limits."""

import hashlib

from onyx.file_processing.zip_index import ZipIndex
from onyx.file_store.models import BundleLimits, BundleMetadata, FileSizeLimitExceeded


def compute_bundle_metadata(
    bundle_bytes: bytes, *, limits: BundleLimits | None = None
) -> BundleMetadata:
    digest = hashlib.sha256()
    total = 0
    count = 0
    # ZipIndex sorts on disk, so memory does not grow with the entry count.
    with ZipIndex(bundle_bytes) as archive:
        for info in archive.sorted_infos():
            if info.is_dir():
                continue
            path = info.filename.encode("utf-8")
            content_hash = hashlib.sha256()
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
                    content_hash.update(chunk)
            digest.update(len(path).to_bytes(8, "big"))
            digest.update(path)
            digest.update(size.to_bytes(8, "big"))
            digest.update(content_hash.digest())
            total += size
            count += 1
    return BundleMetadata(
        content_digest=digest.hexdigest(), unpacked_size_bytes=total, file_count=count
    )
