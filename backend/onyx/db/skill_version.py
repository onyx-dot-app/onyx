from collections.abc import Sequence
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from azure.core.exceptions import ResourceNotFoundError
from botocore.exceptions import ClientError
from google.api_core.exceptions import NotFound
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    FileOrigin,
    OnyxRedisLocks,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import FileRecord, Skill, SkillVersion
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import (
    FileSizeLimitExceeded,
    FileStore,
    is_missing_object,
    s3_error_code,
)
from onyx.file_store.models import BundleLimits, BundleMetadata
from onyx.file_store.staging import delete_files_best_effort
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.skills.bundle import STORED_BUNDLE_LIMITS
from onyx.skills.ingest import (
    IngestedBundle,
    SkillMdRecord,
    bundle_skill_md_record,
)
from onyx.utils.bundle import compute_bundle_metadata
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Uploads save the bundle before the row that uses it commits.
ORPHAN_BUNDLE_MIN_AGE = timedelta(hours=1)
# Bounds one cleanup pass; a backlog clears over later passes.
_ORPHAN_BATCH_SIZE = 500
_ORPHAN_TIME_BUDGET_SECONDS = 30
_ORPHAN_PROGRESS_KEY = "orphan_skill_bundle_cursor"
# Per skill: the version number below which the next metadata repair pass resumes.
_REPAIR_RESUME_KEY_PREFIX = "skill_version_repair_resume:"


class _OrphanCursor(BaseModel):
    created_at: datetime
    file_id: str
    scan_end: tuple[datetime, str] | None = None


def _lock_skill(skill: Skill, db_session: Session) -> None:
    db_session.refresh(skill, with_for_update={"of": Skill})


def current_skill_version(skill: Skill, db_session: Session) -> SkillVersion | None:
    return (
        db_session.get(SkillVersion, skill.current_version_id, populate_existing=True)
        if skill.current_version_id is not None
        else None
    )


def skill_versions(skill: Skill) -> Select[tuple[SkillVersion]]:
    """Newest version number first."""
    return (
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill.id)
        .order_by(SkillVersion.version_number.desc())
    )


def _new_skill_version(skill: Skill) -> SkillVersion:
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Only custom skills have bundle versions"
        )
    return SkillVersion(skill_id=skill.id)


def _publish_skill_version(skill: Skill, version: SkillVersion) -> None:
    skill.current_version_id = version.id
    skill.current_version = version
    skill.bundle_file_id = version.bundle_file_id
    skill.bundle_sha256 = version.bundle_sha256
    skill.is_valid = version.is_valid


# The current version and the newest older versions keep their bundle files.
BUNDLES_KEPT = 10
VERSION_FILES_NOT_KEPT = "The files of this version are no longer kept."


def fill_version_metadata(version: SkillVersion, metadata: BundleMetadata) -> None:
    version.unpacked_size_bytes = metadata.unpacked_size_bytes
    version.file_count = metadata.file_count


def fill_version_skill_md(version: SkillVersion, record: SkillMdRecord) -> None:
    version.name = record.name
    version.frontmatter = record.frontmatter
    version.skill_md = record.skill_md
    if not record.complete:
        # Repair would compute the same values, so it stops retrying.
        version.metadata_unrepairable = True


def read_version_bundle(
    version: SkillVersion, file_store: FileStore, *, max_bytes: int
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
    ) as exc:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT) from exc
    except (ResourceNotFoundError, NotFound, ClientError) as exc:
        if isinstance(exc, ClientError):
            if not is_missing_object(exc):
                raise
            if s3_error_code(exc) in ("NoSuchKey", "NoSuchObject"):
                raise OnyxError(
                    OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT
                ) from exc
        # A provider 404 can name the bucket/container, not the object.
        try:
            file_store.get_file_size(version.bundle_file_id)
        except FileNotFoundError:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT) from exc
        raise


def repair_version_metadata(
    version: SkillVersion,
    file_store: FileStore,
    *,
    limits: BundleLimits,
    verify_bundle: bool = False,
    clear_missing_bundle: bool = False,
) -> bool:
    if version.bundle_file_id is None:
        return False
    # A version marked unrepairable after its sizes were filled kept what
    # PostgreSQL could store of its SKILL.md.
    metadata_complete = (
        version.unpacked_size_bytes is not None
        and version.file_count is not None
        and (version.frontmatter is not None or version.metadata_unrepairable)
    )
    try:
        if metadata_complete and not verify_bundle:
            if clear_missing_bundle:
                return file_store.get_file_size(version.bundle_file_id) is not None
            return True
        bundle_bytes = read_version_bundle(
            version, file_store, max_bytes=limits.max_stored_bytes
        )
    except FileSizeLimitExceeded:
        # Limits are configurable, so a later pass retries after an increase.
        logger.warning("Version bundle exceeds stored byte limit: %s", version.id)
        return False
    except (FileNotFoundError, OnyxError) as exc:
        if isinstance(exc, OnyxError) and exc.error_code != OnyxErrorCode.NOT_FOUND:
            raise
        logger.warning("Version bundle is missing: %s", version.id)
        if clear_missing_bundle:
            version.bundle_file_id = None
        return False
    try:
        metadata = compute_bundle_metadata(bundle_bytes, limits=limits)
    except FileSizeLimitExceeded:
        logger.warning("Version bundle exceeds expanded limits: %s", version.id)
        return False
    except Exception:
        logger.warning("Version bundle cannot be decoded: %s", version.id)
        version.metadata_unrepairable = True
        return False
    fill_version_metadata(version, metadata)
    try:
        # The expanded limits above already bound SKILL.md.
        record = bundle_skill_md_record(bundle_bytes)
    except Exception:
        logger.warning("Version bundle has no root SKILL.md: %s", version.id)
        version.metadata_unrepairable = True
        return False
    version.metadata_unrepairable = False
    fill_version_skill_md(version, record)
    return record.complete


def prune_skill_bundles(skill: Skill, db_session: Session) -> list[str]:
    """Empty the bundle file ids of versions older than the newest kept ones.
    Call under the skill lock; delete the returned files only after commit."""
    current = current_skill_version(skill, db_session)
    cutoff = db_session.scalars(
        skill_versions(skill).offset(BUNDLES_KEPT - 1).limit(1)
    ).first()
    if current is None or cutoff is None:
        return []
    candidates = skill_versions(skill).where(
        SkillVersion.version_number < cutoff.version_number,
        SkillVersion.bundle_file_id.is_not(None),
        SkillVersion.id != current.id,
        # Keep the only recovery source until metadata is complete or cannot be.
        or_(
            SkillVersion.metadata_unrepairable,
            and_(
                SkillVersion.unpacked_size_bytes.is_not(None),
                SkillVersion.file_count.is_not(None),
                SkillVersion.frontmatter.is_not(None),
            ),
        ),
    )
    pruned: list[str] = []
    for version in db_session.scalars(candidates):
        if version.bundle_file_id is None:
            continue
        pruned.append(version.bundle_file_id)
        version.bundle_file_id = None
    db_session.flush()
    return pruned


def write_skill_version(
    skill: Skill,
    *,
    bundle_file_id: str,
    bundle_sha256: str | None,
    is_valid: bool | None,
    metadata: BundleMetadata | None,
    created_by_user_id: UUID | None,
    db_session: Session,
    skill_md: SkillMdRecord | None = None,
) -> SkillVersion:
    """Append and publish atomically; the caller owns commit and staged blob cleanup."""
    with db_session.begin_nested():
        _lock_skill(skill, db_session)
        latest = db_session.scalars(skill_versions(skill).limit(1)).first()
        version = _new_skill_version(skill)
        version.version_number = latest.version_number + 1 if latest else 1
        version.bundle_file_id = bundle_file_id
        version.bundle_sha256 = bundle_sha256
        version.is_valid = is_valid
        version.created_by_user_id = created_by_user_id
        if metadata is not None:
            fill_version_metadata(version, metadata)
        if skill_md is not None:
            fill_version_skill_md(version, skill_md)
        db_session.add(version)
        db_session.flush()
        _publish_skill_version(skill, version)
        db_session.flush()
        return version


def repair_skill_version(skill: Skill, db_session: Session) -> SkillVersion:
    """Legacy columns remain authoritative until all readers use versions."""
    _lock_skill(skill, db_session)
    if not skill.is_custom or skill.bundle_file_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Only custom skills have bundle versions"
        )
    current = current_skill_version(skill, db_session)
    if current is None or (
        current.bundle_file_id,
        current.bundle_sha256,
    ) != (skill.bundle_file_id, skill.bundle_sha256):
        current = write_skill_version(
            skill,
            bundle_file_id=skill.bundle_file_id,
            bundle_sha256=skill.bundle_sha256,
            is_valid=skill.is_valid,
            metadata=None,
            created_by_user_id=None,
            db_session=db_session,
        )
    current.is_valid = skill.is_valid
    return current


def save_skill_version(
    skill: Skill,
    ingested: IngestedBundle,
    creator_id: UUID,
    db_session: Session,
    *,
    initial: bool = False,
) -> list[str]:
    """Returns the pruned bundle files to delete after commit."""
    _lock_skill(skill, db_session)
    if not initial:
        repair_skill_version(skill, db_session)
    write_skill_version(
        skill,
        bundle_file_id=ingested.bundle_file_id,
        bundle_sha256=ingested.bundle_sha256,
        is_valid=True,
        metadata=ingested.metadata,
        created_by_user_id=creator_id,
        db_session=db_session,
        skill_md=ingested.skill_md,
    )
    skill.description = ingested.description
    return prune_skill_bundles(skill, db_session)


def skill_bundle_file_ids(skill: Skill, db_session: Session) -> set[str]:
    file_ids = {
        file_id
        for file_id in db_session.scalars(
            select(SkillVersion.bundle_file_id).where(SkillVersion.skill_id == skill.id)
        )
        if file_id is not None
    }
    # Keep cleanup compatible with pointerless legacy writes until V7.
    if skill.bundle_file_id is not None:
        file_ids.add(skill.bundle_file_id)
    return file_ids


def persist_skill_version_validity(
    *,
    skill_id: UUID,
    version_id: UUID,
    bundle_file_id: str | None,
    is_valid: bool,
    db_session: Session,
) -> None:
    skill = db_session.scalar(
        select(Skill).where(Skill.id == skill_id).with_for_update(of=Skill)
    )
    if skill is None:
        return
    db_session.refresh(
        skill, ["current_version_id", "bundle_file_id", "current_version"]
    )
    if skill.current_version_id != version_id:
        return
    version = skill.current_version
    if (
        version is None
        or version.bundle_file_id != bundle_file_id
        or version.is_valid is not None
    ):
        return
    version.is_valid = is_valid
    if skill.bundle_file_id == bundle_file_id:
        skill.is_valid = is_valid


def _unused_skill_bundles(*conditions: ColumnElement[bool]) -> Select[tuple[str]]:
    """Legacy skill columns count: old writers and pointerless skills use them."""
    return select(FileRecord.file_id).where(
        FileRecord.file_origin == FileOrigin.SKILL_BUNDLE,
        ~exists().where(SkillVersion.bundle_file_id == FileRecord.file_id),
        ~exists().where(Skill.bundle_file_id == FileRecord.file_id),
        *conditions,
    )


def delete_unreferenced_skill_bundles(
    file_ids: Sequence[str], db_session: Session
) -> None:
    """Call after commit. Keeps files that any skill or version still uses."""
    if not file_ids:
        return
    unused = list(
        db_session.scalars(_unused_skill_bundles(FileRecord.file_id.in_(set(file_ids))))
    )
    delete_files_best_effort(unused, context="skill bundle cleanup")


def delete_orphan_skill_bundles() -> int:
    """Delete one batch; wrap the cursor to retry failures after each full scan."""
    lock = get_cache_backend().lock(
        OnyxRedisLocks.ORPHAN_SKILL_BUNDLE_CLEANUP_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        return 0
    try:
        deadline = monotonic() + _ORPHAN_TIME_BUDGET_SECONDS
        store = get_kv_store()
        try:
            progress = store.load(_ORPHAN_PROGRESS_KEY, refresh_cache=True)
        except KvKeyNotFoundError:
            progress = None
        cursor = (
            _OrphanCursor.model_validate(progress) if progress is not None else None
        )
        statement = (
            _unused_skill_bundles(
                FileRecord.created_at < func.now() - ORPHAN_BUNDLE_MIN_AGE
            )
            .add_columns(FileRecord.created_at)
            .order_by(FileRecord.created_at, FileRecord.file_id)
            .limit(_ORPHAN_BATCH_SIZE)
        )
        if cursor is not None:
            statement = statement.where(
                or_(
                    FileRecord.created_at > cursor.created_at,
                    (FileRecord.created_at == cursor.created_at)
                    & (FileRecord.file_id > cursor.file_id),
                )
            )
        with get_session_with_current_tenant() as db_session:
            scan_end = cursor.scan_end if cursor is not None else None
            if scan_end is None:
                last = (
                    db_session.execute(
                        select(FileRecord.created_at, FileRecord.file_id)
                        .where(
                            FileRecord.file_origin == FileOrigin.SKILL_BUNDLE,
                            FileRecord.created_at < func.now() - ORPHAN_BUNDLE_MIN_AGE,
                        )
                        .order_by(
                            FileRecord.created_at.desc(), FileRecord.file_id.desc()
                        )
                        .limit(1)
                    )
                    .tuples()
                    .first()
                )
                scan_end = (last[0], last[1]) if last is not None else None
            if scan_end is not None:
                statement = statement.where(
                    or_(
                        FileRecord.created_at < scan_end[0],
                        (FileRecord.created_at == scan_end[0])
                        & (FileRecord.file_id <= scan_end[1]),
                    )
                )
            rows = list(db_session.execute(statement).tuples())
        deleted = 0
        last_processed: tuple[str, datetime] | None = None
        for file_id, created_at in rows:
            if monotonic() >= deadline:
                break
            lock.extend(CELERY_GENERIC_BEAT_LOCK_TIMEOUT)
            deleted += delete_files_best_effort(
                [file_id], context="orphan skill bundle cleanup"
            )
            lock.extend(CELERY_GENERIC_BEAT_LOCK_TIMEOUT)
            last_processed = (file_id, created_at)
        lock.extend(CELERY_GENERIC_BEAT_LOCK_TIMEOUT)
        if last_processed is not None and scan_end is not None:
            file_id, created_at = last_processed
            store.store(
                _ORPHAN_PROGRESS_KEY,
                {
                    "created_at": created_at.isoformat(),
                    "file_id": file_id,
                    "scan_end": [scan_end[0].isoformat(), scan_end[1]],
                },
            )
        elif not rows:
            store.store(_ORPHAN_PROGRESS_KEY, None)
        return deleted
    finally:
        if lock.owned():
            lock.release()


def skill_version_repair_batch(
    db_session: Session, after: UUID | None, *, drift_only: bool = False
) -> list[Skill]:
    statement = select(Skill).where(Skill.built_in_skill_id.is_(None))
    if drift_only:
        statement = statement.outerjoin(
            SkillVersion, SkillVersion.id == Skill.current_version_id
        ).where(
            or_(
                SkillVersion.id.is_(None),
                SkillVersion.bundle_file_id.is_distinct_from(Skill.bundle_file_id),
                SkillVersion.bundle_sha256.is_distinct_from(Skill.bundle_sha256),
                SkillVersion.is_valid.is_distinct_from(Skill.is_valid),
                exists()
                .where(
                    SkillVersion.skill_id == Skill.id,
                    SkillVersion.bundle_file_id.is_not(None),
                    SkillVersion.metadata_unrepairable.is_(False),
                    or_(
                        SkillVersion.unpacked_size_bytes.is_(None),
                        SkillVersion.file_count.is_(None),
                        SkillVersion.frontmatter.is_(None),
                    ),
                )
                .correlate(Skill),
            )
        )
    if after is not None:
        statement = statement.where(Skill.id > after)
    return list(db_session.scalars(statement.order_by(Skill.id).limit(50)))


def repair_skill_version_metadata(
    skill: Skill,
    db_session: Session,
    file_store: FileStore,
    *,
    deadline: float | None = None,
) -> list[str]:
    """Stops between historical versions at the deadline and saves where it
    stopped. The next pass on this skill starts with the older versions and
    then wraps around, so a slow or failing version cannot block the others.
    Versions left without metadata stay in the drift query, so a later pass
    repairs them."""
    current = repair_skill_version(skill, db_session)
    repair_version_metadata(current, file_store, limits=STORED_BUNDLE_LIMITS)
    kv_store = get_kv_store()
    resume_key = _REPAIR_RESUME_KEY_PREFIX + str(skill.id)
    try:
        resume_below: int | None = int(
            str(kv_store.load(resume_key, refresh_cache=True))
        )
    except (KvKeyNotFoundError, ValueError):
        resume_below = None
    history = list(
        db_session.scalars(skill_versions(skill).where(SkillVersion.id != current.id))
    )
    if resume_below is not None:
        history = [v for v in history if v.version_number < resume_below] + [
            v for v in history if v.version_number >= resume_below
        ]
    stopped_at: int | None = None
    for version in history:
        try:
            with db_session.begin_nested():
                repair_version_metadata(
                    version,
                    file_store,
                    limits=STORED_BUNDLE_LIMITS,
                    clear_missing_bundle=True,
                )
        except Exception:
            logger.exception(
                "Historical skill metadata repair failed for %s", version.id
            )
        if deadline is not None and monotonic() >= deadline:
            stopped_at = version.version_number
            break
    if stopped_at is not None:
        kv_store.store(resume_key, stopped_at)
    elif resume_below is not None:
        try:
            kv_store.delete(resume_key)
        except KvKeyNotFoundError:
            pass
    return prune_skill_bundles(skill, db_session)
