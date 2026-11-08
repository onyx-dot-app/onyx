"""Content metadata for resource bundles with caller-owned expansion limits."""

import hashlib
import io
import zipfile

from pydantic import BaseModel, ConfigDict, Field

from onyx.file_store.models import BundleMetadata, FileSizeLimitExceeded


class BundleLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_stored_bytes: int = Field(ge=0)
    max_file_bytes: int = Field(ge=0)
    max_total_bytes: int = Field(ge=0)


def compute_bundle_metadata(
    bundle_bytes: bytes, *, limits: BundleLimits | None = None
) -> BundleMetadata:
    digest = hashlib.sha256()
    total = 0
    count = 0
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        for info in sorted(archive.infolist(), key=lambda entry: entry.filename):
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
