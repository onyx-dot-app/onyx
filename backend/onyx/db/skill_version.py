from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, select
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import FileRecord, Skill, SkillVersion
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import BundleMetadata
from onyx.file_store.staging import delete_files_best_effort
from onyx.skills.ingest import IngestedBundle, SkillMdRecord


def _lock_skill(skill: Skill, db_session: Session) -> None:
    db_session.refresh(skill, with_for_update=True)


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
    skill.bundle_file_id = version.bundle_file_id
    skill.bundle_sha256 = version.bundle_sha256
    skill.is_valid = version.is_valid


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
) -> None:
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
    db_session.flush()


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
