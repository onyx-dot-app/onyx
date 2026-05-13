"""External-dep unit tests for the skills cleanup sweep.

These exercise the real Postgres + FileStore (S3/MinIO) stack — no mocks. The
sweep's two retention paths (orphan blob, aged soft-delete) are tested
independently and together. Tests bypass time by passing ``retention=0`` (or
a very small window) to the impl, since backdating ``created_at`` on a
``FileRecord`` (server_default=now()) is ugly to do post-insert.
"""

import io
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.skills.tasks import _aged_soft_deleted_skills
from onyx.background.celery.tasks.skills.tasks import _orphan_skill_blob_ids
from onyx.background.celery.tasks.skills.tasks import cleanup_orphaned_skill_blobs_impl
from onyx.configs.constants import FileOrigin
from onyx.db.models import FileRecord
from onyx.db.models import Skill
from onyx.file_store.file_store import get_default_file_store


def _save_skill_bundle_blob(content: bytes = b"PK\x03\x04dummy") -> str:
    """Save a SKILL_BUNDLE blob and return its file_id."""
    return get_default_file_store().save_file(
        content=io.BytesIO(content),
        display_name=f"test-bundle-{uuid4().hex[:8]}.zip",
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )


def _insert_skill(
    db_session: Session,
    *,
    bundle_file_id: str,
    deleted_at: datetime | None = None,
    slug: str | None = None,
) -> Skill:
    skill = Skill(
        slug=slug or f"test-{uuid4().hex[:8]}",
        name="Test skill",
        description="for sweep tests",
        bundle_file_id=bundle_file_id,
        bundle_sha256="0" * 64,
        manifest_metadata={},
        is_public=False,
        enabled=True,
        deleted_at=deleted_at,
    )
    db_session.add(skill)
    db_session.commit()
    db_session.refresh(skill)
    return skill


def _backdate_filerecord(db_session: Session, file_id: str, age: timedelta) -> None:
    """Force ``created_at`` backwards so the retention cutoff fires in tests."""
    record = db_session.execute(
        select(FileRecord).where(FileRecord.file_id == file_id)
    ).scalar_one()
    record.created_at = datetime.now(tz=timezone.utc) - age
    db_session.commit()


def test_orphan_blob_older_than_retention_is_deleted(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    """A SKILL_BUNDLE blob with no referencing Skill row, older than the
    retention window, is removed by the sweep."""
    file_id = _save_skill_bundle_blob()
    _backdate_filerecord(db_session, file_id, timedelta(days=15))

    # Sanity: orphan detector picks it up.
    orphan_ids = _orphan_skill_blob_ids(db_session, timedelta(days=14))
    assert file_id in orphan_ids

    orphans, aged = cleanup_orphaned_skill_blobs_impl(retention=timedelta(days=14))
    assert orphans >= 1
    assert aged == 0

    # Record is gone.
    assert (
        db_session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        ).scalar_one_or_none()
        is None
    )


def test_orphan_blob_within_retention_is_kept(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    """Recently created orphan blobs are NOT swept — they may belong to an
    in-flight upload whose DB commit hasn't landed yet."""
    file_id = _save_skill_bundle_blob()
    # No backdating — record is fresh.

    orphan_ids = _orphan_skill_blob_ids(db_session, timedelta(days=14))
    assert file_id not in orphan_ids

    # Run sweep — should not touch this blob.
    cleanup_orphaned_skill_blobs_impl(retention=timedelta(days=14))
    assert (
        db_session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        ).scalar_one_or_none()
        is not None
    )

    # Cleanup so the next test run starts clean.
    get_default_file_store().delete_file(file_id, error_on_missing=False)


def test_orphan_detector_excludes_referenced_blobs(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    """A blob referenced by an active Skill row is never returned as orphan,
    even when older than the retention cutoff."""
    file_id = _save_skill_bundle_blob()
    _backdate_filerecord(db_session, file_id, timedelta(days=30))
    skill = _insert_skill(db_session, bundle_file_id=file_id)

    try:
        orphan_ids = _orphan_skill_blob_ids(db_session, timedelta(days=14))
        assert file_id not in orphan_ids
    finally:
        db_session.delete(skill)
        db_session.commit()
        get_default_file_store().delete_file(file_id, error_on_missing=False)


def test_aged_soft_deleted_skill_is_hard_deleted_with_blob(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    """A skill whose ``deleted_at`` is older than retention has its blob removed
    AND the row hard-deleted, freeing the slug for reuse."""
    file_id = _save_skill_bundle_blob()
    deleted_at = datetime.now(tz=timezone.utc) - timedelta(days=15)
    skill = _insert_skill(db_session, bundle_file_id=file_id, deleted_at=deleted_at)
    skill_id = skill.id
    slug = skill.slug

    aged = _aged_soft_deleted_skills(db_session, timedelta(days=14))
    assert any(s.id == skill_id for s in aged)

    orphans, aged_deleted = cleanup_orphaned_skill_blobs_impl(
        retention=timedelta(days=14)
    )
    assert aged_deleted >= 1

    # Row is gone.
    assert (
        db_session.execute(
            select(Skill).where(Skill.id == skill_id)
        ).scalar_one_or_none()
        is None
    )
    # Blob is gone.
    assert (
        db_session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        ).scalar_one_or_none()
        is None
    )
    # Slug can now be re-used because the partial unique index excludes deleted
    # rows AND the row itself is hard-deleted.
    _ = orphans  # silence unused
    new_file_id = _save_skill_bundle_blob()
    try:
        _insert_skill(db_session, bundle_file_id=new_file_id, slug=slug)
    finally:
        # Cleanup
        new_skill = db_session.execute(
            select(Skill).where(Skill.slug == slug)
        ).scalar_one()
        db_session.delete(new_skill)
        db_session.commit()
        get_default_file_store().delete_file(new_file_id, error_on_missing=False)


def test_recently_soft_deleted_skill_is_kept(
    db_session: Session, tenant_context: None  # noqa: ARG001
) -> None:
    """A skill soft-deleted within the retention window stays put. Advancing
    ``deleted_at`` past the window then running the sweep again removes it."""
    file_id = _save_skill_bundle_blob()
    # Soft-delete "now".
    skill = _insert_skill(
        db_session,
        bundle_file_id=file_id,
        deleted_at=datetime.now(tz=timezone.utc),
    )
    skill_id = skill.id

    # First sweep — well within retention.
    cleanup_orphaned_skill_blobs_impl(retention=timedelta(days=14))

    refreshed = db_session.execute(
        select(Skill).where(Skill.id == skill_id)
    ).scalar_one_or_none()
    assert refreshed is not None, "soft-deleted skill should still exist"
    assert refreshed.deleted_at is not None

    # Age the soft-delete past retention and re-sweep.
    refreshed.deleted_at = datetime.now(tz=timezone.utc) - timedelta(days=15)
    db_session.commit()

    cleanup_orphaned_skill_blobs_impl(retention=timedelta(days=14))

    assert (
        db_session.execute(
            select(Skill).where(Skill.id == skill_id)
        ).scalar_one_or_none()
        is None
    )
    assert (
        db_session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        ).scalar_one_or_none()
        is None
    )
