"""Push skill bundles to running sandboxes."""

import io
import zipfile
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import list_skills_for_user
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.db.sandbox import get_sandbox_user_map
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import PushResult
from onyx.utils.logger import setup_logger

logger = setup_logger()

SKILLS_MOUNT_PATH = "/workspace/managed/skills"


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Extract all visible skill bundles into a ``{slug}/`` directory tree."""
    skills = list_skills_for_user(user=user, db_session=db_session)
    file_store = get_default_file_store()

    files: FileSet = {}
    for skill in skills:
        try:
            blob = file_store.read_file(skill.bundle_file_id)
            zip_bytes = blob.read()
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    files[f"{skill.slug}/{info.filename}"] = zf.read(info)
        except Exception:
            logger.warning(
                "Failed to read bundle for skill %s (%s), skipping",
                skill.slug,
                skill.bundle_file_id,
            )
    return files


def hydrate_sandbox_skills(
    sandbox_id: UUID,
    user: User,
    db_session: Session,
) -> PushResult:
    """Push all visible skills to a single sandbox (cold-start hydration)."""
    files = build_skills_fileset_for_user(user, db_session)
    return get_sandbox_manager().push_to_sandbox(
        sandbox_id=sandbox_id,
        mount_path=SKILLS_MOUNT_PATH,
        files=files,
    )


def push_skill_to_affected_sandboxes(skill: Skill, db_session: Session) -> None:
    """Resolve affected users for *skill* and push updated filesets."""
    user_ids = affected_user_ids_for_skill(skill, db_session)
    push_skills_for_users(user_ids, db_session)


def push_skills_for_users(user_ids: set[UUID], db_session: Session) -> None:
    """Rebuild and push the full skills fileset for each user's sandbox."""
    if not user_ids:
        return
    try:
        sandbox_map = get_sandbox_user_map(list(user_ids), db_session)
        sandbox_files = {
            sid: build_skills_fileset_for_user(user, db_session)
            for sid, user in sandbox_map.items()
        }
        result = get_sandbox_manager().push_to_sandboxes(
            mount_path=SKILLS_MOUNT_PATH,
            sandbox_files=sandbox_files,
        )
        if result.failures:
            logger.warning(
                "Skill push partially failed: %d/%d sandboxes",
                len(result.failures),
                result.targets,
            )
    except Exception:
        logger.exception("Failed to push skills to sandboxes")
