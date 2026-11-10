from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    FileOrigin,
    OnyxRedisLocks,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import FileRecord, Skill, SkillVersion, User
from onyx.db.resource_version import (
    ResourceVersionAdapter,
    fill_version_metadata,
    prune_resource_bundles,
    repair_version_metadata,
    write_resource_version,
)
from onyx.db.skill_mutation import assert_skill_content_editable
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.file_store.models import BundleMetadata
from onyx.file_store.staging import delete_files_best_effort
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.skills.bundle import STORED_BUNDLE_LIMITS
from onyx.skills.ingest import IngestedBundle
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Uploads save the bundle before the row that uses it commits.
ORPHAN_BUNDLE_MIN_AGE = timedelta(hours=1)
# Bounds one cleanup pass; a backlog clears over later passes.
_ORPHAN_BATCH_SIZE = 500
_ORPHAN_TIME_BUDGET_SECONDS = 30
_ORPHAN_PROGRESS_KEY = "orphan_skill_bundle_cursor"


class _OrphanCursor(BaseModel):
    created_at: datetime
    file_id: str
    scan_end: tuple[datetime, str] | None = None


@dataclass(frozen=True)
class SkillContentSnapshot:
    skill_id: UUID
    current_version_id: UUID | None
    current_bundle_file_id: str | None
    current_bundle_sha256: str | None
    bundle_file_id: str | None
    bundle_sha256: str | None
    name: str
    description: str


def skill_content_snapshot(skill: Skill) -> SkillContentSnapshot:
    current = skill.current_version
    return SkillContentSnapshot(
        skill.id,
        skill.current_version_id,
        current.bundle_file_id if current else None,
        current.bundle_sha256 if current else None,
        skill.bundle_file_id,
        skill.bundle_sha256,
        skill.name,
        skill.description,
    )


@dataclass(frozen=True)
class PreparedSkillVersionWrite:
    observation: SkillContentSnapshot
    metadata: tuple[str, int, int] | None


def _prepare_metadata(
    version: SkillVersion, file_store: FileStore, *, verify_bundle: bool = False
) -> tuple[str, int, int] | None:
    # A transient copy prevents reads and autoflush from writing observed rows.
    observed = SkillVersion(
        id=version.id,
        bundle_file_id=version.bundle_file_id,
        bundle_sha256=version.bundle_sha256,
        content_digest=version.content_digest,
        unpacked_size_bytes=version.unpacked_size_bytes,
        file_count=version.file_count,
    )
    if not repair_version_metadata(
        observed, file_store, limits=STORED_BUNDLE_LIMITS, verify_bundle=verify_bundle
    ):
        return None
    if (
        observed.content_digest is None
        or observed.unpacked_size_bytes is None
        or observed.file_count is None
    ):
        return None
    return observed.content_digest, observed.unpacked_size_bytes, observed.file_count


def _legacy_version(skill: Skill) -> SkillVersion:
    current = skill.current_version
    if current is not None and (current.bundle_file_id, current.bundle_sha256) == (
        skill.bundle_file_id,
        skill.bundle_sha256,
    ):
        return current
    return SkillVersion(
        bundle_file_id=skill.bundle_file_id, bundle_sha256=skill.bundle_sha256
    )


def prepare_skill_version_write(
    skill: Skill, ingested: IngestedBundle, db_session: Session
) -> PreparedSkillVersionWrite:
    """Read previous content before taking any resource or membership lock."""
    with db_session.no_autoflush:
        observation = skill_content_snapshot(skill)
        previous = _legacy_version(skill)
        metadata = _prepare_metadata(
            previous,
            get_default_file_store(),
            verify_bundle=previous.content_digest == ingested.metadata.content_digest,
        )
    return PreparedSkillVersionWrite(observation, metadata)


def _apply_metadata(version: SkillVersion, metadata: tuple[str, int, int]) -> None:
    fill_version_metadata(
        version,
        BundleMetadata(
            content_digest=metadata[0],
            unpacked_size_bytes=metadata[1],
            file_count=metadata[2],
        ),
    )


class SkillVersionAdapter(ResourceVersionAdapter[SkillVersion]):
    def __init__(self, skill: Skill) -> None:
        self.skill = skill

    def lock(self, db_session: Session) -> None:
        db_session.refresh(self.skill, with_for_update={"of": Skill})

    def current(self, db_session: Session) -> SkillVersion | None:
        return (
            db_session.get(
                SkillVersion, self.skill.current_version_id, populate_existing=True
            )
            if self.skill.current_version_id is not None
            else None
        )

    def versions(self) -> Select[tuple[SkillVersion]]:
        return (
            select(SkillVersion)
            .where(SkillVersion.skill_id == self.skill.id)
            .order_by(SkillVersion.version_number.desc())
        )

    def new_version(self) -> SkillVersion:
        if not self.skill.is_custom:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Only custom skills have bundle versions"
            )
        return SkillVersion(skill_id=self.skill.id)

    def publish(self, version: SkillVersion) -> None:
        self.skill.current_version_id = version.id
        self.skill.current_version = version
        self.skill.bundle_file_id = version.bundle_file_id
        self.skill.bundle_sha256 = version.bundle_sha256
        self.skill.is_valid = version.is_valid


def list_skill_versions(
    skill: Skill, db_session: Session, *, before_version: int | None = None
) -> list[tuple[SkillVersion, User | None, bool]]:
    """List up to 50 versions of an authorized skill, newest first."""
    statement = (
        SkillVersionAdapter(skill)
        .versions()
        .add_columns(User, (SkillVersion.id == Skill.current_version_id).is_(True))
        .join(Skill, SkillVersion.skill_id == Skill.id)
        .outerjoin(User, SkillVersion.created_by_user_id == User.id)
        .limit(50)
    )
    if before_version is not None:
        statement = statement.where(SkillVersion.version_number < before_version)
    return [
        (version, creator, is_current)
        for version, creator, is_current in db_session.execute(statement).unique()
    ]


def fetch_skill_version(
    skill: Skill, version_id: UUID, db_session: Session
) -> SkillVersion:
    """Resolve a version only within the caller's authorized skill."""
    version = db_session.scalar(
        SkillVersionAdapter(skill).versions().where(SkillVersion.id == version_id)
    )
    if version is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill version not found")
    return version


def assert_skill_version_bundle_unchanged(
    skill: Skill,
    version_id: UUID,
    bundle_file_id: str | None,
    db_session: Session,
) -> None:
    """Recheck the restore source after the caller locks its Skill."""
    version = fetch_skill_version(skill, version_id, db_session)
    db_session.refresh(version)
    if version.bundle_file_id != bundle_file_id:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Version files changed. Retry this request."
        )


def repair_skill_version(skill: Skill, db_session: Session) -> SkillVersion:
    """Legacy columns remain authoritative until all readers use versions."""
    adapter = SkillVersionAdapter(skill)
    adapter.lock(db_session)
    if not skill.is_custom or skill.bundle_file_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Only custom skills have bundle versions"
        )
    current = adapter.current(db_session)
    if current is None or (
        current.bundle_file_id,
        current.bundle_sha256,
    ) != (skill.bundle_file_id, skill.bundle_sha256):
        current = write_resource_version(
            adapter,
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
    prepared: PreparedSkillVersionWrite | None = None,
) -> list[str]:
    """Returns the bundle files to delete after commit: pruned bundles and the
    staged upload when the current version is reused."""
    assert_skill_content_editable(skill)
    if not initial and prepared is None:
        prepared = prepare_skill_version_write(skill, ingested, db_session)
    adapter = SkillVersionAdapter(skill)
    adapter.lock(db_session)
    db_session.refresh(skill, ["current_version"])
    assert_skill_content_editable(skill)
    if ingested.canonical_name != skill.name:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "A skill name cannot change across versions."
        )
    reuse_current = False
    if not initial:
        matches = (
            prepared is not None
            and prepared.observation == skill_content_snapshot(skill)
        )
        current = repair_skill_version(skill, db_session)
        if matches and prepared is not None and prepared.metadata is not None:
            _apply_metadata(current, prepared.metadata)
            reuse_current = True
    version = write_resource_version(
        adapter,
        bundle_file_id=ingested.bundle_file_id,
        bundle_sha256=ingested.bundle_sha256,
        is_valid=True,
        metadata=ingested.metadata,
        created_by_user_id=creator_id,
        db_session=db_session,
        reuse_current=reuse_current,
    )
    skill.description = ingested.description
    stale_file_ids = prune_resource_bundles(adapter, db_session)
    if version.bundle_file_id != ingested.bundle_file_id:
        stale_file_ids.append(ingested.bundle_file_id)
    return stale_file_ids


def skill_bundle_file_ids(skill: Skill, db_session: Session) -> set[str]:
    return skill_bundle_file_ids_for_skills([skill], db_session)


def skill_bundle_file_ids_for_skills(
    skills: Sequence[Skill], db_session: Session
) -> set[str]:
    file_ids = {
        file_id
        for file_id in db_session.scalars(
            select(SkillVersion.bundle_file_id).where(
                SkillVersion.skill_id.in_([skill.id for skill in skills])
            )
        )
        if file_id is not None
    }
    # Keep cleanup compatible with pointerless legacy writes until V7.
    file_ids.update(
        skill.bundle_file_id for skill in skills if skill.bundle_file_id is not None
    )
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
                scan_end = tuple(last) if last is not None else None
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
                    or_(
                        SkillVersion.content_digest.is_(None),
                        SkillVersion.unpacked_size_bytes.is_(None),
                        SkillVersion.file_count.is_(None),
                    ),
                )
                .correlate(Skill),
            )
        )
    if after is not None:
        statement = statement.where(Skill.id > after)
    return list(db_session.scalars(statement.order_by(Skill.id).limit(50)))


def repair_skill_version_metadata(
    skill: Skill, db_session: Session, file_store: FileStore
) -> list[str]:
    adapter = SkillVersionAdapter(skill)
    with db_session.no_autoflush:
        db_session.refresh(skill)
        observation = skill_content_snapshot(skill)
        versions = list(db_session.scalars(adapter.versions()))
        prepared: dict[UUID, tuple[str | None, str | None, SkillVersion]] = {}
        for version in versions:
            observed = SkillVersion(
                id=version.id,
                bundle_file_id=version.bundle_file_id,
                bundle_sha256=version.bundle_sha256,
                content_digest=version.content_digest,
                unpacked_size_bytes=version.unpacked_size_bytes,
                file_count=version.file_count,
            )
            try:
                with db_session.begin_nested():
                    repair_version_metadata(
                        observed,
                        file_store,
                        limits=STORED_BUNDLE_LIMITS,
                        clear_missing_bundle=version.id
                        != observation.current_version_id,
                    )
            except Exception:
                logger.exception(
                    "Skill version metadata repair failed for %s", version.id
                )
                continue
            prepared[version.id] = (
                version.bundle_file_id,
                version.bundle_sha256,
                observed,
            )
        previous = _legacy_version(skill)
        legacy_metadata = _prepare_metadata(previous, file_store)
    adapter.lock(db_session)
    db_session.refresh(skill, ["current_version"])
    if observation != skill_content_snapshot(skill):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Skill content changed. Retry metadata repair."
        )
    current = repair_skill_version(skill, db_session)
    for version in db_session.scalars(
        adapter.versions().execution_options(populate_existing=True)
    ):
        observed = prepared.get(version.id)
        if (
            observed is not None
            and (version.bundle_file_id, version.bundle_sha256) == observed[:2]
        ):
            repaired = observed[2]
            if repaired.bundle_file_id is None:
                version.bundle_file_id = None
            elif (
                repaired.content_digest is not None
                and repaired.unpacked_size_bytes is not None
                and repaired.file_count is not None
            ):
                _apply_metadata(
                    version,
                    (
                        repaired.content_digest,
                        repaired.unpacked_size_bytes,
                        repaired.file_count,
                    ),
                )
    if current.bundle_file_id is not None and legacy_metadata is not None:
        _apply_metadata(current, legacy_metadata)
    return prune_resource_bundles(adapter, db_session)
