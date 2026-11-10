"""Helpers for reading skill source content."""

from onyx.db.models import Skill
from onyx.db.resource_version import read_version_bundle
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.zip_limits import ZipMetadataLimitError
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.file_store.models import FileSizeLimitExceeded
from onyx.skills.built_in import BuiltInSkillDefinition
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    STORED_BUNDLE_LIMITS,
    TEMPLATE_SUFFIX,
    _bundle_limit_error,
    read_custom_bundle_instructions,
    strip_skill_md_frontmatter,
)
from onyx.utils.bundle import compute_bundle_metadata


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
    *,
    path: str = SKILL_MD_NAME,
    max_bytes: int | None = None,
    max_metadata_bytes: int | None = None,
) -> str:
    bundle_bytes = read_custom_skill_bundle_bytes(
        skill, file_store, max_metadata_bytes=max_metadata_bytes
    )
    return read_custom_bundle_instructions(
        bundle_bytes,
        path=path,
        max_bytes=max_bytes,
        max_metadata_bytes=max_metadata_bytes,
    )


def read_custom_skill_bundle_bytes(
    skill: Skill,
    file_store: FileStore | None = None,
    *,
    max_metadata_bytes: int | None = None,
) -> bytes:
    if skill.current_version is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Custom skill '{skill.name}' has no current version.",
        )
    try:
        try:
            bundle_bytes = read_version_bundle(
                skill.current_version,
                file_store or get_default_file_store(),
                max_bytes=STORED_BUNDLE_LIMITS.max_stored_bytes,
            )
        except FileSizeLimitExceeded as exc:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                f"Stored bundle for skill '{skill.name}' exceeds the "
                f"{STORED_BUNDLE_LIMITS.max_stored_bytes}-byte read limit.",
            ) from exc
        compute_bundle_metadata(
            bundle_bytes,
            limits=STORED_BUNDLE_LIMITS,
            max_metadata_bytes=max_metadata_bytes,
        )
    except ZipMetadataLimitError as exc:
        limit = max_metadata_bytes or 0
        raise _bundle_limit_error(
            "zip_metadata_bytes",
            limit,
            f"Skill bundle zip file list exceeds the {limit // (1024 * 1024)} MiB limit.",
        ) from exc
    except (OnyxError, FileSizeLimitExceeded):
        raise
    except Exception as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            f"Failed to read bundle for skill '{skill.name}'.",
        ) from exc
    return bundle_bytes
