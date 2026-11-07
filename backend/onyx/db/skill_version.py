from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import FileRecord, Skill, SkillVersion
from onyx.db.resource_version import (
    ResourceVersionAdapter,
    prune_resource_bundles,
    repair_version_metadata,
    write_resource_version,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.skills.ingest import IngestedBundle
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Uploads save the bundle before the row that uses it commits.
ORPHAN_BUNDLE_MIN_AGE = timedelta(hours=1)
# Bounds one cleanup pass; a backlog clears over later passes.
_ORPHAN_BATCH_SIZE = 500


class SkillVersionAdapter(ResourceVersionAdapter[SkillVersion]):
    def __init__(self, skill: Skill) -> None:
        self.skill = skill

    def lock(self, db_session: Session) -> None:
        db_session.refresh(self.skill, with_for_update=True)

    def current(self, db_session: Session) -> SkillVersion | None:
        return (
            db_session.get(SkillVersion, self.skill.current_version_id)
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
        self.skill.bundle_file_id = version.bundle_file_id
        self.skill.bundle_sha256 = version.bundle_sha256
        self.skill.is_valid = version.is_valid


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
) -> list[str]:
    """Returns the bundle files to delete after commit: pruned bundles and the
    staged upload when the current version is reused."""
    adapter = SkillVersionAdapter(skill)
    adapter.lock(db_session)
    reuse_current = False
    if not initial:
        current = repair_skill_version(skill, db_session)
        try:
            reuse_current = repair_version_metadata(
                current,
                get_default_file_store(),
                verify_bundle=current.content_digest
                == ingested.metadata.content_digest,
            )
        except Exception:
            logger.warning("Could not read previous skill version: %s", current.id)
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
    """Deletes one batch of old skill bundle files that nothing uses. Returns
    how many it deleted."""
    with get_session_with_current_tenant() as db_session:
        file_ids = list(
            db_session.scalars(
                _unused_skill_bundles(
                    FileRecord.created_at < func.now() - ORPHAN_BUNDLE_MIN_AGE
                )
                .order_by(FileRecord.created_at)
                .limit(_ORPHAN_BATCH_SIZE)
            )
        )
    return delete_files_best_effort(file_ids, context="orphan skill bundle cleanup")
