"""Validation for custom skill bundles already stored in FileStore."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Final

from onyx.db.models import Skill
from onyx.db.skill_version import is_missing_bundle_error
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.file_store.models import FileSizeLimitExceeded
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    STORED_BUNDLE_LIMITS,
    NormalizedSkillBundle,
    check_stored_zip_size,
    normalize_custom_bundle,
    read_bundle_file,
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


def load_stored_custom_skill_bundle(
    bundle_file_id: str,
    file_store: FileStore,
) -> NormalizedSkillBundle:
    # Lower upload limits without lowering the allowance for existing bundles.
    check_stored_zip_size(
        _stored_object_size(bundle_file_id, file_store),
        STORED_BUNDLE_LIMITS.max_stored_bytes,
    )
    bundle_stream = file_store.read_file(
        bundle_file_id, max_bytes=STORED_BUNDLE_LIMITS.max_stored_bytes
    )
    try:
        bundle_bytes = read_bundle_file(
            bundle_stream, max_bytes=STORED_BUNDLE_LIMITS.max_stored_bytes
        )
    finally:
        bundle_stream.close()
    return normalize_custom_bundle(
        bundle_bytes, zip_max_bytes=None, max_file_count=None
    )


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
    version = skill.current_version
    if version is None or version.bundle_file_id is None:
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="custom skill has no stored bundle",
        )

    try:
        normalized = load_stored_custom_skill_bundle(
            version.bundle_file_id,
            file_store,
        )
    except Exception as exc:
        try:
            missing = is_missing_bundle_error(exc, version.bundle_file_id, file_store)
        except Exception:
            missing = False
        if missing:
            return SkillValidationResult(
                is_valid=False,
                normalized_bundle=None,
                detail="stored bundle does not exist",
            )
        # Settings errors and size limits follow configuration, which can
        # change, so they leave the skill unclassified instead of invalid.
        if isinstance(exc, FileSizeLimitExceeded) or (
            isinstance(exc, OnyxError) and exc.error_code in _CONFIG_ERROR_CODES
        ):
            detail = exc.detail if isinstance(exc, OnyxError) else str(exc)
            return SkillValidationResult(
                is_valid=None,
                normalized_bundle=None,
                detail=f"stored bundle is outside the configured limits: {detail}",
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
        with zipfile.ZipFile(io.BytesIO(normalized.content)) as bundle_zip:
            raw_skill_md = bundle_zip.read(SKILL_MD_NAME)
        document = parse_skill_document(
            raw_skill_md,
            directory_name=normalized.source_directory,
        )
    except (OnyxError, KeyError, zipfile.BadZipFile) as exc:
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
