"""Size metadata for resource bundles."""

import io
import zipfile

from onyx.file_store.models import BundleMetadata


def compute_bundle_metadata(bundle_bytes: bytes) -> BundleMetadata:
    total = 0
    count = 0
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            size = 0
            with archive.open(info) as source:
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
            total += size
            count += 1
    return BundleMetadata(unpacked_size_bytes=total, file_count=count)
