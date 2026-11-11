"""Validation for custom skill bundles already stored in FileStore."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from typing import Final

from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import Skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import (
    DEFAULT_STORED_ZIP_MAX_BYTES,
    NormalizedSkillBundle,
    check_stored_zip_size,
    normalize_custom_bundle,
    read_bundle_file,
    read_bundle_skill_md,
)
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import SKILL_NAME_PATTERN

_CONFIG_ERROR_CODES: Final[frozenset[OnyxErrorCode]] = frozenset(
    {OnyxErrorCode.SERVICE_UNAVAILABLE, OnyxErrorCode.PAYLOAD_TOO_LARGE}
)


@dataclass(frozen=True)
class SkillValidationResult:
    is_valid: bool | None
    normalized_bundle: bytes | None
    detail: str | None = None


def _stored_object_size(bundle_file_id: str, file_store: FileStore) -> int | None:
    """Object metadata, or None so the bounded read reports any failure."""
    try:
        size = file_store.get_file_size(bundle_file_id)
    except Exception:
        return None
    return size if isinstance(size, int) else None


def read_stored_bundle_bytes(bundle_file_id: str, file_store: FileStore) -> bytes:
    """Read a saved bundle under the stored ZIP allowance; overflow is a 413."""
    # Lower upload limits without lowering the allowance for existing bundles.
    check_stored_zip_size(
        _stored_object_size(bundle_file_id, file_store), DEFAULT_STORED_ZIP_MAX_BYTES
    )
    bundle_stream = file_store.read_file(bundle_file_id)
    try:
        return read_bundle_file(bundle_stream, max_bytes=DEFAULT_STORED_ZIP_MAX_BYTES)
    finally:
        bundle_stream.close()


def load_stored_custom_skill_bundle(
    bundle_file_id: str,
    file_store: FileStore,
) -> NormalizedSkillBundle:
    bundle_bytes = read_stored_bundle_bytes(bundle_file_id, file_store)
    return normalize_custom_bundle(
        bundle_bytes, zip_max_bytes=None, max_file_count=None, stored_read=True
    )


def _is_missing_file_error(exc: Exception) -> bool:
    if isinstance(exc, FileRecordNotFoundError):
        return True

    response = getattr(exc, "response", None)  # ods: ignore[getattr]
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict) and str(error.get("Code")) in {
            "404",
            "NoSuchKey",
            "NoSuchObject",
            "NotFound",
        }:
            return True
    return getattr(exc, "code", None) == 404  # ods: ignore[getattr]


def validate_stored_custom_skill(
    skill: Skill,
    file_store: FileStore,
) -> SkillValidationResult:
    if len(skill.name) > 64 or not SKILL_NAME_PATTERN.fullmatch(skill.name):
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="persisted skill name does not match the canonical grammar",
        )
    if skill.name in BUILT_IN_SKILLS:
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="persisted skill name is reserved for a built-in skill",
        )
    if skill.bundle_file_id is None:
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="custom skill has no stored bundle",
        )

    try:
        normalized = load_stored_custom_skill_bundle(
            skill.bundle_file_id,
            file_store,
        )
    except Exception as exc:
        if _is_missing_file_error(exc):
            return SkillValidationResult(
                is_valid=False,
                normalized_bundle=None,
                detail="stored bundle does not exist",
            )
        # Settings errors and size limits follow configuration, which can
        # change, so they leave the skill unclassified instead of invalid.
        if isinstance(exc, OnyxError) and exc.error_code in _CONFIG_ERROR_CODES:
            return SkillValidationResult(
                is_valid=None,
                normalized_bundle=None,
                detail=f"stored bundle is outside the configured limits: {exc.detail}",
            )
        if isinstance(exc, OnyxError):
            return SkillValidationResult(
                is_valid=False,
                normalized_bundle=None,
                detail=f"stored bundle is invalid: {exc.detail}",
            )
        return SkillValidationResult(
            is_valid=None,
            normalized_bundle=None,
            detail=f"stored bundle could not be read: {exc}",
        )

    try:
        document = parse_skill_document(
            read_bundle_skill_md(normalized.content),
            directory_name=normalized.source_directory,
        )
    except (OnyxError, KeyError, zipfile.BadZipFile) as exc:
        if (
            isinstance(exc, OnyxError)
            and exc.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
        ):
            return SkillValidationResult(
                is_valid=None,
                normalized_bundle=None,
                detail=f"stored bundle could not be read: {exc.detail}",
            )
        detail = exc.detail if isinstance(exc, OnyxError) else str(exc)
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail=f"stored bundle is invalid: {detail}",
        )

    if document.metadata.name != skill.name:
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="SKILL.md name does not match the persisted skill name",
        )

    return SkillValidationResult(
        is_valid=True,
        normalized_bundle=normalized.content,
    )
