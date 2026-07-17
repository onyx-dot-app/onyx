"""Push skill bundles to running sandboxes."""

import io
import zipfile
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.external_app import get_external_app_by_skill_id
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import list_skills
from onyx.db.skill import persist_skill_validity
from onyx.db.skill import SkillAccessPolicy
from onyx.db.skill import SkillValidityUpdate
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.db.sandbox import get_sandbox_user_map
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import PushResult
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_skills_section_from_data,
)
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.built_in import COMPANY_SEARCH
from onyx.skills.built_in import EXTERNAL_APP_SKILL_ID_TO_APP_TYPE
from onyx.skills.rendering import render_company_search_skill
from onyx.skills.rendering import render_external_app_skill
from onyx.skills.validation import load_stored_custom_skill_bundle
from onyx.skills.validation import validate_stored_custom_skill
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


def _add_static_builtin(
    files: FileSet, skill: Skill, definition: BuiltInSkillDefinition
) -> None:
    source_dir = definition.source_dir
    for path in source_dir.rglob("*"):
        if not path.is_file() or _is_excluded(path, source_dir):
            continue
        rel = path.relative_to(source_dir)
        files[f"{skill.slug}/{rel.as_posix()}"] = path.read_bytes()


def _render_template(
    files: FileSet,
    skill: Skill,
    definition: BuiltInSkillDefinition,
    db_session: Session,
    user: User,
) -> None:
    """Overwrite ``{slug}/SKILL.md`` with a per-user rendering. company-search
    and external-app built-ins have renderers; any other templated built-in logs
    a warning and ships the static siblings as-is."""
    if definition.built_in_skill_id == COMPANY_SEARCH.built_in_skill_id:
        rendered = render_company_search_skill(
            db_session, user, definition.source_dir.parent
        )
        files[f"{skill.slug}/SKILL.md"] = rendered.encode("utf-8")
        return

    app_type = EXTERNAL_APP_SKILL_ID_TO_APP_TYPE.get(definition.built_in_skill_id)
    if app_type is not None:
        external_app = get_external_app_by_skill_id(db_session, skill.id)
        rendered = render_external_app_skill(
            db_session,
            app_type,
            external_app,
            definition.source_dir,
        )
        files[f"{skill.slug}/SKILL.md"] = rendered.encode("utf-8")
        return

    logger.warning(
        "Built-in %s has_template=True but no renderer", definition.built_in_skill_id
    )


def _add_bundle_bytes(files: FileSet, skill: Skill, bundle_bytes: bytes) -> bool:
    try:
        bundle_files: FileSet = {}
        with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                bundle_files[f"{skill.slug}/{info.filename}"] = zf.read(info)
        files.update(bundle_files)
        return True
    except Exception:
        logger.warning(
            "Failed to unpack bundle for skill %s (%s), skipping",
            skill.slug,
            skill.bundle_file_id,
            exc_info=True,
        )
        return False


def _assemble_fileset(
    skills: Iterable[Skill],
    user: User,
    db_session: Session,
) -> tuple[list[Skill], FileSet]:
    """Return hydrated skills and their flat ``{path: bytes}`` map.

    Built-ins render from disk. Custom rows must already be valid or pass lazy
    validation before their FileStore bundle is unpacked. Invalid,
    indeterminate, and unknown built-in rows are skipped.
    """
    files: FileSet = {}
    hydrated_skills: list[Skill] = []
    validity_updates: list[SkillValidityUpdate] = []
    file_store = get_default_file_store()

    for skill in skills:
        if skill.built_in_skill_id is None:
            if skill.is_valid is False:
                continue

            if skill.is_valid is None:
                validation = validate_stored_custom_skill(skill, file_store)
                if validation.is_valid is not None:
                    validity_updates.append(
                        SkillValidityUpdate(
                            skill_id=skill.id,
                            bundle_file_id=skill.bundle_file_id,
                            is_valid=validation.is_valid,
                        )
                    )
                if validation.normalized_bundle is None:
                    logger.warning(
                        "Skipping unvalidated skill %s: %s",
                        skill.id,
                        validation.detail,
                    )
                    continue
                bundle_bytes = validation.normalized_bundle
            else:
                try:
                    if skill.bundle_file_id is None:
                        continue
                    bundle_bytes = load_stored_custom_skill_bundle(
                        skill.bundle_file_id,
                        file_store,
                    ).content
                except Exception as exc:
                    logger.warning(
                        "Skipping unreadable valid skill %s: %s",
                        skill.id,
                        exc,
                    )
                    continue

            if _add_bundle_bytes(files, skill, bundle_bytes):
                hydrated_skills.append(skill)
            continue
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            logger.warning(
                "Skill row %s references unknown built-in %s; skipping",
                skill.slug,
                skill.built_in_skill_id,
            )
            continue
        hydrated_skills.append(skill)
        _add_static_builtin(files, skill, definition)
        if definition.has_template:
            _render_template(files, skill, definition, db_session, user)

    try:
        persist_skill_validity(validity_updates)
    except Exception:
        logger.exception("Failed to persist skill validity classifications")
    return hydrated_skills, files


def build_skills_fileset_for_user(user: User, db_session: Session) -> FileSet:
    """Return a flat ``{path: bytes}`` map of every skill the user can see."""
    skills = list_skills(
        policy=SkillAccessPolicy.USE,
        user=user,
        db_session=db_session,
    )
    _, files = _assemble_fileset(skills, user, db_session)
    return files


def build_user_skills_payload(
    user: User, db_session: Session
) -> tuple[str, str, FileSet]:
    """Return (skills_section, connectable_apps_section, fileset) sharing one set
    of DB reads. ``connectable_apps_section`` lists org apps the user hasn't
    connected yet, so the agent knows they exist and can offer to set one up via
    the connect tool."""
    skills = list_skills(
        policy=SkillAccessPolicy.USE,
        user=user,
        db_session=db_session,
    )
    hydrated_skills, files = _assemble_fileset(skills, user, db_session)
    skills_section = build_skills_section_from_data(hydrated_skills)
    connectable_apps_section = build_connectable_apps_list(
        get_connectable_apps_for_user(db_session, user)
    )
    return skills_section, connectable_apps_section, files


def hydrate_sandbox_skills(
    sandbox_id: UUID,
    user: User,
    db_session: Session,
    *,
    sandbox_manager: SandboxManager,
    files: FileSet | None = None,
) -> PushResult:
    """Push all visible skills to a single sandbox (cold-start hydration)."""
    if files is None:
        files = build_skills_fileset_for_user(user, db_session)
    return sandbox_manager.push_to_sandbox(
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
        for failure in result.failures:
            logger.warning(
                "Skill push failed for sandbox %s: %s: %s",
                failure.sandbox_id,
                failure.reason,
                failure.detail,
            )
    except Exception:
        logger.exception("Failed to push skills to sandboxes")
