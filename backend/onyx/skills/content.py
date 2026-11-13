"""Helpers for reading skill source content."""

from collections.abc import Collection, Iterator
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.plugin import get_stored_version_content, get_visible_versions_skill_md
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    TEMPLATE_SUFFIX,
    custom_bundle_contents_from_stored,
    inspect_custom_bundle,
    strip_skill_md_frontmatter,
)
from onyx.skills.models import CustomSkillBundleContents
from onyx.skills.validation import read_stored_bundle_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


def iter_builtin_skill_files(source_dir: Path) -> Iterator[Path]:
    """Yield source files, excluding hidden paths and Python caches."""
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(
            part == "__pycache__" or part.startswith(".")
            for part in path.relative_to(source_dir).parts
        ):
            continue
        yield path


def read_builtin_skill_instructions(definition: BuiltInSkillDefinition) -> str:
    source_path = definition.source_dir / SKILL_MD_NAME
    if not source_path.is_file():
        source_path = definition.source_dir / f"{SKILL_MD_NAME}{TEMPLATE_SUFFIX}"
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


def read_versions_instructions(
    version_ids: Collection[UUID],
    user_id: UUID,
    db_session: Session,
) -> dict[UUID, str]:
    """The SKILL.md instructions of each version whose skill the user can see
    now, from one query. A version that stores no SKILL.md text (one copied
    from a legacy skill row) opens its bundle. A version that is gone, hidden
    from the user or unreadable is left out."""
    if not version_ids:
        return {}
    instructions: dict[UUID, str] = {}
    for version_id, stored in get_visible_versions_skill_md(
        version_ids, user_id, db_session
    ).items():
        if stored.skill_md is not None:
            instructions[version_id] = strip_skill_md_frontmatter(stored.skill_md)
            continue
        try:
            instructions[version_id] = inspect_custom_bundle(
                read_skill_bundle_blob(stored.bundle_file_id, str(version_id))
            ).instructions_markdown
        except OnyxError:
            logger.warning(
                "Could not read the bundle of skill version %s",
                version_id,
                exc_info=True,
            )
    return instructions
