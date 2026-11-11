import io
from collections.abc import Container, Iterator
from contextlib import contextmanager
from typing import NamedTuple

from onyx.configs.constants import FileOrigin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    build_single_file_bundle,
    compute_bundle_sha256,
    normalize_custom_bundle,
    read_bundle_skill_md,
)
from onyx.skills.metadata import parse_skill_document
from onyx.utils.logger import setup_logger

logger = setup_logger()


class IngestedBundle(NamedTuple):
    canonical_name: str
    bundle_file_id: str
    bundle_sha256: str
    description: str


def save_skill_bundle_bytes(
    bundle_bytes: bytes,
    *,
    display_name: str,
    file_store: FileStore,
) -> str:
    return file_store.save_file(
        content=io.BytesIO(bundle_bytes),
        display_name=display_name,
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )


def ingest_skill_bundle(
    bundle_bytes: bytes,
    filename: str | None,
    file_store: FileStore,
    *,
    expected_name: str | None = None,
    uncapped_paths: Container[str] | None = None,
) -> IngestedBundle:
    """Validate, parse, hash, and store a custom skill bundle.

    Accepts either a ZIP bundle or a standalone ``SKILL.md``. Standalone files
    use their frontmatter ``name`` as canonical identity and are stored as ZIPs.

    Pass ``expected_name`` to keep an existing row's identity when replacing a
    bundle. On creation, both ZIPs and standalone files use the validated
    frontmatter name; the upload filename is not an identity source.

    Prefer ``ingested_skill_bundle`` when the stored blob should be cleaned up
    automatically if the caller's transaction fails.
    ``uncapped_paths`` skips the path caps for paths an edit kept unchanged.
    """
    is_standalone_skill_md = filename is not None and filename.lower() == "skill.md"
    if is_standalone_skill_md:
        bundle_bytes = build_single_file_bundle(SKILL_MD_NAME, bundle_bytes)

    normalized = normalize_custom_bundle(bundle_bytes, uncapped_paths=uncapped_paths)
    document = parse_skill_document(
        read_bundle_skill_md(normalized.content),
        directory_name=normalized.source_directory,
    )
    name = document.metadata.name
    description = document.metadata.description
    if expected_name is not None and name != expected_name:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Replacement SKILL.md frontmatter field 'name' must remain "
            f"'{expected_name}'",
        )
    if name in BUILT_IN_SKILLS:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"skill name '{name}' is reserved",
        )
    sha = compute_bundle_sha256(normalized.content)

    bundle_file_id = save_skill_bundle_bytes(
        normalized.content,
        display_name=f"{name}.zip",
        file_store=file_store,
    )
    return IngestedBundle(
        canonical_name=name,
        bundle_file_id=bundle_file_id,
        bundle_sha256=sha,
        description=description,
    )


@contextmanager
def ingested_skill_bundle(
    bundle_bytes: bytes,
    filename: str | None,
    file_store: FileStore,
    *,
    expected_name: str | None = None,
    uncapped_paths: Container[str] | None = None,
) -> Iterator[IngestedBundle]:
    ingested = ingest_skill_bundle(
        bundle_bytes,
        filename,
        file_store,
        expected_name=expected_name,
        uncapped_paths=uncapped_paths,
    )
    try:
        yield ingested
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise


def delete_bundle_blob(file_store: FileStore, file_id: str) -> None:
    """Best-effort cleanup of a stored bundle blob we no longer reference."""
    try:
        file_store.delete_file(file_id, error_on_missing=False)
    except Exception:
        logger.warning("Failed to delete bundle blob %s", file_id, exc_info=True)
