"""Bundle history shared by skills and other versioned resources."""

import hashlib
import io
import zipfile
from typing import Protocol
from uuid import UUID

from azure.core.exceptions import ResourceNotFoundError
from botocore.exceptions import ClientError
from google.api_core.exceptions import NotFound
from sqlalchemy import Select
from sqlalchemy.orm import Session

from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import BundleVersionMixin
from onyx.file_store.file_store import FileStore
from onyx.file_store.models import BundleMetadata
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ResourceVersionAdapter[Version: BundleVersionMixin](Protocol):
    """Resource mapping; versions() must order newest version number first."""

    def lock(self, db_session: Session) -> None: ...
    def current(self, db_session: Session) -> Version | None: ...
    def versions(self) -> Select[tuple[Version]]: ...
    def new_version(self) -> Version: ...
    def publish(self, version: Version) -> None: ...


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


def fill_version_metadata(
    version: BundleVersionMixin, metadata: BundleMetadata
) -> None:
    version.content_digest = metadata.content_digest
    version.unpacked_size_bytes = metadata.unpacked_size_bytes
    version.file_count = metadata.file_count


def repair_version_metadata(version: BundleVersionMixin, file_store: FileStore) -> None:
    if version.bundle_file_id is None or all(
        value is not None
        for value in (
            version.content_digest,
            version.unpacked_size_bytes,
            version.file_count,
        )
    ):
        return
    try:
        with file_store.read_file(version.bundle_file_id) as source:
            metadata = compute_bundle_metadata(source.read())
    except (
        FileRecordNotFoundError,
        FileNotFoundError,
        ResourceNotFoundError,
        NotFound,
    ):
        logger.warning("Version bundle is missing: %s", version.id)
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("NoSuchKey", "404"):
            raise
        logger.warning("Version bundle is missing: %s", version.id)
        return
    except zipfile.BadZipFile:
        logger.warning("Version bundle is not a ZIP: %s", version.id)
        return
    fill_version_metadata(version, metadata)


def write_resource_version[Version: BundleVersionMixin](
    adapter: ResourceVersionAdapter[Version],
    *,
    bundle_file_id: str,
    bundle_sha256: str | None,
    is_valid: bool | None,
    metadata: BundleMetadata | None,
    created_by_user_id: UUID | None,
    db_session: Session,
    marketplace_revision: str | None = None,
) -> Version:
    """Append and publish atomically; the caller owns commit and staged blob cleanup."""
    with db_session.begin_nested():
        adapter.lock(db_session)
        current = adapter.current(db_session)
        if (
            current is not None
            and metadata is not None
            and (current.content_digest == metadata.content_digest)
        ):
            return current
        latest = db_session.scalars(adapter.versions().limit(1)).first()
        version = adapter.new_version()
        version.version_number = latest.version_number + 1 if latest else 1
        version.bundle_file_id = bundle_file_id
        version.bundle_sha256 = bundle_sha256
        version.is_valid = is_valid
        version.created_by_user_id = created_by_user_id
        version.marketplace_revision = marketplace_revision
        if metadata is not None:
            fill_version_metadata(version, metadata)
        db_session.add(version)
        db_session.flush()
        adapter.publish(version)
        db_session.flush()
        return version
