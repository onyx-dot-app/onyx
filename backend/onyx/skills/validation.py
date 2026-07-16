"""Validation for custom skill bundles already stored in FileStore."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import Skill
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import normalize_custom_bundle
from onyx.skills.bundle import NormalizedSkillBundle
from onyx.skills.bundle import read_bundle_file
from onyx.skills.bundle import SKILL_MD_NAME
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import SKILL_NAME_PATTERN


@dataclass(frozen=True)
class SkillValidationResult:
    is_valid: bool | None
    normalized_bundle: bytes | None
    detail: str | None = None


def load_stored_custom_skill_bundle(
    bundle_file_id: str,
    file_store: FileStore,
) -> NormalizedSkillBundle:
    bundle_stream = file_store.read_file(bundle_file_id)
    try:
        bundle_bytes = read_bundle_file(bundle_stream)
    finally:
        bundle_stream.close()
    return normalize_custom_bundle(bundle_bytes)


def _is_missing_file_error(exc: Exception) -> bool:
    if isinstance(exc, FileRecordNotFoundError):
        return True

    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict) and str(error.get("Code")) in {
            "404",
            "NoSuchKey",
            "NoSuchObject",
            "NotFound",
        }:
            return True
    return getattr(exc, "code", None) == 404


def validate_stored_custom_skill(
    skill: Skill,
    file_store: FileStore,
) -> SkillValidationResult:
    if len(skill.slug) > 64 or not SKILL_NAME_PATTERN.fullmatch(skill.slug):
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="persisted skill name does not match the canonical grammar",
        )
    if skill.slug in BUILT_IN_SKILLS:
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

    if document.metadata.name != skill.slug:
        return SkillValidationResult(
            is_valid=False,
            normalized_bundle=None,
            detail="SKILL.md name does not match the persisted skill name",
        )

    return SkillValidationResult(
        is_valid=True,
        normalized_bundle=normalized.content,
    )
