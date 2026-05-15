"""Push skill bundles to running sandboxes."""

import io
import zipfile
from pathlib import Path
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
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_skills_section_from_data,
)
from onyx.skills.registry import BuiltinSkill
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.skills.rendering import render_company_search_skill
from onyx.utils.logger import setup_logger

logger = setup_logger()

SKILLS_MOUNT_PATH = "/workspace/managed/skills"

_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({"__pycache__"})


def _is_excluded(path: Path, source_dir: Path) -> bool:
    """True if any path component is excluded or starts with a dot."""
    rel = path.relative_to(source_dir)
    for part in rel.parts:
        if part in _EXCLUDED_DIR_NAMES or part.startswith("."):
            return True
    return False


def _add_static_builtin(files: FileSet, skill: BuiltinSkill) -> None:
    """Walk *skill.source_dir* and add every regular file under ``{slug}/``."""
    source_dir = skill.source_dir
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if _is_excluded(path, source_dir):
            continue
        rel = path.relative_to(source_dir)
        files[f"{skill.slug}/{rel.as_posix()}"] = path.read_bytes()


def _add_template_builtin(
    files: FileSet,
    skill: BuiltinSkill,
    db_session: Session,
    user: User,
) -> None:
    """Render *skill*'s template per-user and add it under ``{slug}/SKILL.md``.

    Only the ``company-search`` slug is currently template-driven. Adding new
    template skills requires a branch here — premature to design a plugin
    system for one skill.
    """
    if skill.slug == "company-search":
        rendered = render_company_search_skill(
            db_session, user, skill.source_dir.parent
        )
        files[f"{skill.slug}/SKILL.md"] = rendered.encode("utf-8")
        return

    logger.warning(
        "Built-in skill %s has_template=True but no renderer; skipping",
        skill.slug,
    )


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Return a flat ``{path: bytes}`` map of every skill the user can see.

    Built-in skills are read from disk (the API server image bakes the
    template directory in); custom skills are extracted from their FileStore
    bundle. Both land under a ``{slug}/`` prefix so the sandbox's symlink at
    ``/workspace/managed/skills`` shows them as siblings.
    """
    files: FileSet = {}

    # Built-ins are validated at boot (register_builtin_skills) — let any
    # failure here propagate, since it means the image is broken.
    for builtin in BuiltinSkillRegistry.instance().list_available(db_session):
        if builtin.has_template:
            _add_template_builtin(files, builtin, db_session, user)
        else:
            _add_static_builtin(files, builtin)

    customs = list_skills_for_user(user=user, db_session=db_session)
    file_store = get_default_file_store()
    for skill in customs:
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


def build_skills_section_for_user(user: User, db_session: Session) -> str:
    """Render the AGENTS.md ``{{AVAILABLE_SKILLS_SECTION}}`` for *user*.

    Pulls visible built-ins from the registry + customs from the DB, then
    formats them via ``build_skills_section_from_data``. Sandbox managers
    receive the rendered string; they never touch the DB themselves.
    """
    builtins = BuiltinSkillRegistry.instance().list_available(db_session)
    customs = list_skills_for_user(user=user, db_session=db_session)
    return build_skills_section_from_data(builtins, customs)


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
