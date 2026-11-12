"""Content of plugin versions copied from legacy skill rows, read from their
stored bundles by the same rules as a save."""

from dataclasses import dataclass

from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    build_skill_version_content,
    check_skill_md_size,
    compute_bundle_sha256,
    open_bundle_zip,
)
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import PluginVersionContent
from onyx.skills.validation import validate_stored_custom_skill


@dataclass(frozen=True)
class StoredVersionRepair:
    # Set when the bundle is valid.
    content: PluginVersionContent | None
    is_valid: bool | None
    over_limits: bool
    detail: str | None


def read_stored_version_content(
    name: str, bundle_file_id: str, file_store: FileStore
) -> StoredVersionRepair:
    """The content a save stores for this bundle. A SKILL.md that a version
    cannot store in the database keeps ``skill_md`` empty, so readers open the
    bundle. ``is_valid`` is None when the bundle is over a size limit or could
    not be read."""
    result = validate_stored_custom_skill(name, bundle_file_id, file_store)
    if not result.is_valid or result.normalized_bundle is None:
        return StoredVersionRepair(
            content=None,
            is_valid=result.is_valid,
            over_limits=result.over_limits,
            detail=result.detail,
        )
    with open_bundle_zip(result.normalized_bundle) as bundle_zip:
        raw_skill_md = bundle_zip.read(SKILL_MD_NAME)
    content = build_skill_version_content(
        result.normalized_bundle,
        bundle_file_id=bundle_file_id,
        bundle_sha256=compute_bundle_sha256(result.normalized_bundle),
        raw_skill_md=raw_skill_md,
        document=parse_skill_document(raw_skill_md),
    )
    try:
        check_skill_md_size(raw_skill_md)
    except OnyxError:
        content = content.model_copy(
            update={
                "skills": [
                    skill.model_copy(update={"skill_md": None})
                    for skill in content.skills
                ]
            }
        )
    return StoredVersionRepair(
        content=content, is_valid=True, over_limits=False, detail=None
    )
