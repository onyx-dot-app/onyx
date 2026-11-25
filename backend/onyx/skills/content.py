"""Helpers for reading skill source content."""

from collections.abc import Callable, Collection, Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.plugin import (
    SkillKey,
    get_skills_bundle_paths,
    get_stored_version_content,
    get_visible_versions_skill_md,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.prompts.skill_prompts import (
    BUILT_IN_SKILL_FILES_LINE,
    CUSTOM_SKILL_FILES_LINE,
)
from onyx.server.features.build.sandbox.models import chat_skill_folder
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    BuiltInSkillDefinition,
    iter_builtin_skill_files,
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
from onyx.tools.constants import LOAD_SKILL_TOOL_NAME
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


def has_other_files(paths: Iterable[str]) -> bool:
    """Whether a skill folder's paths, relative to it, name a file besides
    SKILL.md."""
    return any(
        path not in (SKILL_MD_NAME, f"{SKILL_MD_NAME}{TEMPLATE_SUFFIX}")
        for path in paths
    )


def custom_skills_with_files(
    skills: Collection[ChatSkill], db_session: Session
) -> set[SkillKey]:
    """The custom skills among `skills` with files besides SKILL.md, which
    load_skill copies into the sandbox. A version with no file list may have
    files, so it counts."""
    keys = {
        (skill.version_id, skill.path)
        for skill in skills
        if skill.built_in_skill_id is None
    }
    if not keys:
        return set()
    bundle_paths = get_skills_bundle_paths(keys, db_session)
    with_files: set[SkillKey] = set()
    for key in keys:
        paths = bundle_paths.get(key)
        prefix = f"{key[1]}/" if key[1] else ""
        if paths is None or has_other_files(
            path.removeprefix(prefix) for path in paths if path.startswith(prefix)
        ):
            with_files.add(key)
    return with_files


def read_chat_skills_md(
    skills: Collection[ChatSkill],
    user_id: UUID,
    db_session: Session,
    *,
    with_sandbox: bool,
    called_name: Callable[[str], str],
) -> dict[SkillKey, str]:
    """``with_sandbox`` (a chat with the sandbox tools): a custom skill's text
    names its VM folder, and a skill with files besides SKILL.md starts with
    the line that says where they are and how to use them. That line names
    load_skill by `called_name`."""
    custom_keys = {
        (skill.version_id, skill.path)
        for skill in skills
        if skill.built_in_skill_id is None
    }
    skill_md = read_versions_skill_md(custom_keys, user_id, db_session)
    with_files = custom_skills_with_files(skills, db_session) if with_sandbox else set()
    for skill in skills:
        folder = chat_skill_folder(skill.name)
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id or "")
        if definition is None:
            key = (skill.version_id, skill.path)
            if with_sandbox and key in skill_md:
                text = resolve_skill_dir_placeholder(skill_md[key], folder)
                if key in with_files:
                    text = (
                        CUSTOM_SKILL_FILES_LINE.format(
                            folder=folder,
                            load_tool=called_name(LOAD_SKILL_TOOL_NAME),
                        )
                        + text
                    )
                skill_md[key] = text
            continue
        try:
            instructions = read_builtin_skill_instructions(definition, skill.path)
        except OnyxError:
            logger.warning("Could not read built-in skill %s", skill.name)
            continue
        source_dir = definition.source_dir / skill.path
        if has_other_files(
            path.relative_to(source_dir).as_posix()
            for path in iter_builtin_skill_files(source_dir)
        ):
            instructions = (
                BUILT_IN_SKILL_FILES_LINE.format(folder=folder) + instructions
            )
        skill_md[(skill.version_id, skill.path)] = instructions
    return skill_md
