"""Bundle history shared by skills and other versioned resources."""

from typing import Protocol
from uuid import UUID

from azure.core.exceptions import ResourceNotFoundError
from botocore.exceptions import ClientError
from google.api_core.exceptions import NotFound
from sqlalchemy import Select
from sqlalchemy.orm import Session

from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import BundleVersionMixin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import (
    FileSizeLimitExceeded,
    FileStore,
    is_missing_object,
)
from onyx.file_store.models import BundleLimits, BundleMetadata
from onyx.utils.bundle import compute_bundle_metadata
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The current version and the newest older versions keep their bundle files.
BUNDLES_KEPT = 10
VERSION_FILES_NOT_KEPT = "The files of this version are no longer kept."


class ResourceVersionAdapter[Version: BundleVersionMixin](Protocol):
    """Resource mapping; versions() must order newest version number first."""

    def lock(self, db_session: Session) -> None: ...
    def current(self, db_session: Session) -> Version | None: ...
    def versions(self) -> Select[tuple[Version]]: ...
    def new_version(self) -> Version: ...
    def publish(self, version: Version) -> None: ...


def fill_version_metadata(
    version: BundleVersionMixin, metadata: BundleMetadata
) -> None:
    version.content_digest = metadata.content_digest
    version.unpacked_size_bytes = metadata.unpacked_size_bytes
    version.file_count = metadata.file_count


def read_version_bundle(
    version: BundleVersionMixin, file_store: FileStore, *, max_bytes: int
) -> bytes:
    """Raises NOT_FOUND when pruning removed the bundle, also during a race."""
    if version.bundle_file_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT)
    try:
        with file_store.read_file(
            version.bundle_file_id, max_bytes=max_bytes
        ) as source:
            return source.read()
    except (
        FileRecordNotFoundError,
        FileNotFoundError,
        ResourceNotFoundError,
        NotFound,
    ) as exc:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT) from exc
    except ClientError as exc:
        if not is_missing_object(exc):
            raise
        raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT) from exc


def repair_version_metadata(
    version: BundleVersionMixin,
    file_store: FileStore,
    *,
    limits: BundleLimits,
    verify_bundle: bool = False,
) -> bool:
    if version.bundle_file_id is None:
        return False
    if not verify_bundle and all(
        value is not None
        for value in (
            version.content_digest,
            version.unpacked_size_bytes,
            version.file_count,
        )
    ):
        return True
    try:
        bundle_bytes = read_version_bundle(
            version, file_store, max_bytes=limits.max_stored_bytes
        )
    except FileSizeLimitExceeded:
        logger.warning("Version bundle exceeds stored byte limit: %s", version.id)
        return False
    except OnyxError as exc:
        if exc.error_code != OnyxErrorCode.NOT_FOUND:
            raise
        logger.warning("Version bundle is missing: %s", version.id)
        return False
    try:
        metadata = compute_bundle_metadata(bundle_bytes, limits=limits)
    except Exception:
        logger.warning("Version bundle cannot be decoded: %s", version.id)
        return False
    if (
        version.content_digest is not None
        and version.content_digest != metadata.content_digest
    ):
        logger.warning("Version bundle content changed: %s", version.id)
        return False
    fill_version_metadata(version, metadata)
    return True


def prune_resource_bundles[Version: BundleVersionMixin](
    adapter: ResourceVersionAdapter[Version], db_session: Session
) -> list[str]:
    """Empty the bundle file ids of versions older than the newest kept ones.
    Call under the adapter lock; delete the returned files only after commit."""
    current = adapter.current(db_session)
    cutoff = db_session.scalars(
        adapter.versions().offset(BUNDLES_KEPT - 1).limit(1)
    ).first()
    if current is None or cutoff is None:
        return []
    version_model = type(cutoff)
    candidates = adapter.versions().where(
        version_model.version_number < cutoff.version_number,
        version_model.bundle_file_id.is_not(None),
        version_model.id != current.id,
    )
    pruned: list[str] = []
    for version in db_session.scalars(candidates):
        if version.bundle_file_id is None:
            continue
        pruned.append(version.bundle_file_id)
        version.bundle_file_id = None
    db_session.flush()
    return pruned


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
    reuse_current: bool = False,
) -> Version:
    """Append and publish atomically; the caller owns commit and staged blob cleanup."""
    with db_session.begin_nested():
        adapter.lock(db_session)
        current = adapter.current(db_session)
        if (
            reuse_current
            and current is not None
            and metadata is not None
            and (current.content_digest == metadata.content_digest)
        ):
            current.is_valid = is_valid
            adapter.publish(current)
            db_session.flush()
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
