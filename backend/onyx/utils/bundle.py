"""Content metadata for validated resource bundles."""

import hashlib
import io
import zipfile

from onyx.file_store.models import BundleMetadata


def compute_bundle_metadata(bundle_bytes: bytes) -> BundleMetadata:
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
                while chunk := source.read(64 * 1024):
                    content_hash.update(chunk)
                    size += len(chunk)
            digest.update(len(path).to_bytes(8, "big"))
            digest.update(path)
            digest.update(size.to_bytes(8, "big"))
            digest.update(content_hash.digest())
            total += size
            count += 1
    return BundleMetadata(
        content_digest=digest.hexdigest(), unpacked_size_bytes=total, file_count=count
    )
