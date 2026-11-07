from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from onyx.db.models import Skill, SkillVersion
from onyx.db.resource_version import (
    ResourceVersionAdapter,
    repair_version_metadata,
    write_resource_version,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.ingest import IngestedBundle
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
) -> bool:
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
    db_session.flush()
    return version.bundle_file_id == ingested.bundle_file_id
