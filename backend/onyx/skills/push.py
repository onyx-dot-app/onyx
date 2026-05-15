"""Push skill bundles to running sandboxes."""

import io
import zipfile
from collections.abc import Iterable
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
    rel = path.relative_to(source_dir)
    for part in rel.parts:
        if part in _EXCLUDED_DIR_NAMES or part.startswith("."):
            return True
    # Template sources are rendered separately; never ship them raw.
    if path.suffix == ".template":
        return True
    return False


def _add_static_builtin(files: FileSet, skill: BuiltinSkill) -> None:
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
    # Static siblings first so the renderer's SKILL.md write wins.
    _add_static_builtin(files, skill)

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


def _assemble_fileset(
    builtins: Iterable[BuiltinSkill],
    customs: Iterable[Skill],
    user: User,
    db_session: Session,
) -> FileSet:
    files: FileSet = {}

    for builtin in builtins:
        if builtin.has_template:
            _add_template_builtin(files, builtin, db_session, user)
        else:
            _add_static_builtin(files, builtin)

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


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Return a flat ``{path: bytes}`` map of every skill the user can see."""
    builtins = BuiltinSkillRegistry.instance().list_available(db_session)
    customs = list_skills_for_user(user=user, db_session=db_session)
    return _assemble_fileset(builtins, customs, user, db_session)


def build_user_skills_payload(user: User, db_session: Session) -> tuple[str, FileSet]:
    """Return (skills_section, fileset) sharing one set of DB reads."""
    builtins = BuiltinSkillRegistry.instance().list_available(db_session)
    customs = list_skills_for_user(user=user, db_session=db_session)
    section = build_skills_section_from_data(builtins, customs)
    files = _assemble_fileset(builtins, customs, user, db_session)
    return section, files


def hydrate_sandbox_skills(
    sandbox_id: UUID,
    user: User,
    db_session: Session,
    files: FileSet | None = None,
) -> PushResult:
    """Push all visible skills to a single sandbox (cold-start hydration)."""
    if files is None:
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
