"""Helpers for reading skill source content."""

from collections.abc import Iterator
from pathlib import Path

from onyx.db.models import Skill, SkillVersion
from onyx.db.skill_version import read_version_bundle
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.file_store.models import FileSizeLimitExceeded
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    STORED_BUNDLE_LIMITS,
    TEMPLATE_SUFFIX,
    read_custom_bundle_instructions,
    strip_skill_md_frontmatter,
)
from onyx.utils.bundle import compute_bundle_metadata


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


def read_custom_skill_bundle_instructions(
    skill: Skill,
    file_store: FileStore | None = None,
) -> str:
    bundle_bytes = read_custom_skill_bundle_bytes(skill, file_store)
    return read_custom_bundle_instructions(bundle_bytes)


def read_stored_version_bundle(
    skill: Skill, version: SkillVersion, file_store: FileStore
) -> bytes:
    """Read a version under the stored ZIP allowance; overflow is a 413."""
    try:
        return read_version_bundle(
            version, file_store, max_bytes=STORED_BUNDLE_LIMITS.max_stored_bytes
        )
    except FileSizeLimitExceeded as exc:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"Stored bundle for skill '{skill.name}' exceeds the "
            f"{STORED_BUNDLE_LIMITS.max_stored_bytes}-byte read limit.",
        ) from exc


def read_custom_skill_bundle_bytes(
    skill: Skill,
    file_store: FileStore | None = None,
) -> bytes:
    if skill.current_version is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Custom skill '{skill.name}' has no current version.",
        )
    try:
        bundle_bytes = read_stored_version_bundle(
            skill, skill.current_version, file_store or get_default_file_store()
        )
        try:
            compute_bundle_metadata(bundle_bytes, limits=STORED_BUNDLE_LIMITS)
        except FileSizeLimitExceeded as exc:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                f"Stored bundle for skill '{skill.name}' exceeds the expanded "
                f"limits of {STORED_BUNDLE_LIMITS.max_file_bytes} bytes per file "
                f"and {STORED_BUNDLE_LIMITS.max_total_bytes} bytes in total.",
            ) from exc
    except OnyxError as exc:
        # Pruning never removes the current bundle, so a missing one is a fault.
        if exc.error_code == OnyxErrorCode.NOT_FOUND:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                f"Failed to read bundle for skill '{skill.name}'.",
            ) from exc
        raise
    except Exception as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Failed to read bundle for skill '{skill.name}'.",
        ) from exc
    return bundle_bytes
