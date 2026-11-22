"""Helpers for reading skill source content."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.plugin import (
    SkillKey,
    get_stored_version_content,
    get_visible_versions_skill_md,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.prompts.skill_prompts import SKILL_FILES_LINE
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    CHAT_SKILLS_PATH,
    BuiltInSkillDefinition,
)
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    TEMPLATE_SUFFIX,
    custom_bundle_contents_from_stored,
    inspect_custom_bundle,
    read_stored_bundle,
    strip_skill_md_frontmatter,
)
from onyx.skills.models import ChatSkill, CustomSkillBundleContents
from onyx.skills.rendering import resolve_skill_dir_placeholder
from onyx.skills.validation import read_stored_bundle_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


def read_builtin_skill_instructions(
    definition: BuiltInSkillDefinition, path: str = ""
) -> str:
    source_dir = definition.source_dir / path
    source_path = source_dir / SKILL_MD_NAME
    if not source_path.is_file():
        source_path = source_dir / f"{SKILL_MD_NAME}{TEMPLATE_SUFFIX}"
    if not source_path.is_file():
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Built-in skill '{definition.built_in_skill_id}' has no SKILL.md source.",
        )
    try:
        return strip_skill_md_frontmatter(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Failed to read built-in skill '{definition.built_in_skill_id}'.",
        ) from exc


def read_skill_bundle_blob(
    bundle_file_id: str | None,
    skill_name: str,
    file_store: FileStore | None = None,
) -> bytes:
    if bundle_file_id is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Custom skill '{skill_name}' has no bundle.",
        )
    store = file_store or get_default_file_store()
    try:
        bundle_bytes = read_stored_bundle_bytes(bundle_file_id, store)
    except OnyxError:
        raise
    except Exception as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Failed to read bundle for skill '{skill_name}'.",
        ) from exc
    return bundle_bytes


def read_version_contents(
    version_id: UUID,
    db_session: Session,
    file_store: FileStore | None = None,
) -> CustomSkillBundleContents:
    """The SKILL.md instructions and file list of one plugin version. Reads the
    database, and opens the bundle only for a version that stores no file list
    or SKILL.md text yet (one copied from a legacy skill row)."""
    stored = get_stored_version_content(version_id, db_session)
    if stored.file_manifest is not None and stored.skill_md is not None:
        return custom_bundle_contents_from_stored(stored.skill_md, stored.file_manifest)
    return inspect_custom_bundle(
        read_skill_bundle_blob(
            stored.bundle_file_id, stored.name or str(version_id), file_store
        )
    )


def read_versions_skill_md(
    skills: Collection[SkillKey],
    user_id: UUID,
    db_session: Session,
) -> dict[SkillKey, str]:
    if not skills:
        return {}
    skill_md: dict[SkillKey, str] = {}
    for key, stored in get_visible_versions_skill_md(
        skills, user_id, db_session
    ).items():
        if stored.skill_md is not None:
            skill_md[key] = stored.skill_md
            continue
        version_id, path = key
        if path:
            continue
        try:
            skill_md[key], _ = read_stored_bundle(
                read_skill_bundle_blob(stored.bundle_file_id, str(version_id))
            )
        except OnyxError:
            logger.warning(
                "Could not read the bundle of skill version %s",
                version_id,
                exc_info=True,
            )
    return skill_md


def read_chat_skills_md(
    skills: Collection[ChatSkill],
    user_id: UUID,
    db_session: Session,
    *,
    sandbox: bool,
) -> dict[SkillKey, str]:
    """With ``sandbox``, a custom skill's text names its VM folder."""
    skill_md = read_versions_skill_md(
        {
            (skill.version_id, skill.path)
            for skill in skills
            if skill.built_in_skill_id is None
        },
        user_id,
        db_session,
    )
    for skill in skills:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id or "")
        if definition is None:
            key = (skill.version_id, skill.path)
            if sandbox and key in skill_md:
                folder = f"{CHAT_SKILLS_PATH}/{skill.name}"
                skill_md[key] = SKILL_FILES_LINE.format(
                    folder=folder
                ) + resolve_skill_dir_placeholder(skill_md[key], folder)
            continue
        try:
            instructions = read_builtin_skill_instructions(definition, skill.path)
        except OnyxError:
            logger.warning("Could not read built-in skill %s", skill.name)
            continue
        skill_md[(skill.version_id, skill.path)] = (
            SKILL_FILES_LINE.format(folder=f"{CHAT_SKILLS_PATH}/{skill.name}")
            + instructions
        )
    return skill_md
