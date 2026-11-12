"""Helpers for reading skill source content."""

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.plugin import StoredVersionContent, get_stored_version_content
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
from onyx.skills.validation import is_missing_file_error, read_stored_bundle_bytes


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


VERSION_FILES_NOT_KEPT = "The files of this version are no longer kept."


def read_skill_bundle_blob(
    bundle_file_id: str | None,
    skill_name: str,
    file_store: FileStore | None = None,
) -> bytes:
    """A pruned bundle raises NOT_FOUND, also when the prune wins a race with
    this read."""
    if bundle_file_id is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT)
    store = file_store or get_default_file_store()
    try:
        bundle_bytes = read_stored_bundle_bytes(bundle_file_id, store)
    except OnyxError:
        raise
    except Exception as exc:
        if is_missing_file_error(exc):
            raise OnyxError(OnyxErrorCode.NOT_FOUND, VERSION_FILES_NOT_KEPT) from exc
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Failed to read bundle for skill '{skill_name}'.",
        ) from exc
    return bundle_bytes


def _stored_version_content(
    version_id: UUID, db_session: Session
) -> StoredVersionContent:
    stored = get_stored_version_content(version_id, db_session)
    if stored is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill version not found.")
    return stored


def read_version_bundle_bytes(
    version_id: UUID,
    db_session: Session,
    file_store: FileStore | None = None,
) -> bytes:
    return _stored_bundle_bytes(
        _stored_version_content(version_id, db_session), file_store
    )


def _stored_bundle_bytes(
    stored: StoredVersionContent, file_store: FileStore | None
) -> bytes:
    return read_skill_bundle_blob(
        stored.bundle_file_id, stored.name or str(stored.version_id), file_store
    )


def read_version_contents(
    version_id: UUID,
    db_session: Session,
    file_store: FileStore | None = None,
) -> CustomSkillBundleContents:
    """The SKILL.md instructions and file list of one plugin version. Reads the
    database, and opens the bundle only for a version that stores no file list
    or SKILL.md text yet (one copied from a legacy skill row)."""
    return _version_contents(
        _stored_version_content(version_id, db_session), file_store
    )


def read_version_preview(
    version_id: UUID, db_session: Session
) -> tuple[StoredVersionContent, CustomSkillBundleContents]:
    """The stored name and description of one version, with its contents as
    ``read_version_contents`` reads them."""
    stored = _stored_version_content(version_id, db_session)
    return stored, _version_contents(stored, None)


def _version_contents(
    stored: StoredVersionContent, file_store: FileStore | None
) -> CustomSkillBundleContents:
    if stored.file_manifest is not None and stored.skill_md is not None:
        return custom_bundle_contents_from_stored(stored.skill_md, stored.file_manifest)
    return inspect_custom_bundle(_stored_bundle_bytes(stored, file_store))
