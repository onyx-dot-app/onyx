import io
from typing import NamedTuple

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import FileStore
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import parse_skill_md_metadata
from onyx.skills.bundle import slug_from_filename
from onyx.skills.bundle import validate_custom_bundle
from onyx.utils.logger import setup_logger

logger = setup_logger()


class IngestedBundle(NamedTuple):
    slug: str
    bundle_file_id: str
    bundle_sha256: str
    name: str
    description: str


def ingest_skill_bundle(
    bundle_bytes: bytes,
    filename: str | None,
    file_store: FileStore,
    *,
    slug: str | None = None,
) -> IngestedBundle:
    """Validate, parse, hash, and store a custom skill bundle.

    Validates the zip structure, parses ``(name, description)`` from SKILL.md
    frontmatter, hashes the bytes, and saves the blob.

    Pass ``slug`` to keep an existing row's slug when replacing a bundle on
    update; when omitted the slug is derived from ``filename`` (create path).

    The caller owns DB row creation and must delete ``bundle_file_id`` if its
    transaction fails.
    """
    if slug is None:
        slug = slug_from_filename(filename)
    validate_custom_bundle(bundle_bytes, slug=slug)
    name, description = parse_skill_md_metadata(bundle_bytes)
    sha = compute_bundle_sha256(bundle_bytes)

    bundle_file_id = file_store.save_file(
        content=io.BytesIO(bundle_bytes),
        display_name=f"{slug}.zip",
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )
    return IngestedBundle(
        slug=slug,
        bundle_file_id=bundle_file_id,
        bundle_sha256=sha,
        name=name,
        description=description,
    )


def delete_bundle_blob(file_store: FileStore, file_id: str) -> None:
    """Best-effort cleanup of a stored bundle blob we no longer reference."""
    try:
        file_store.delete_file(file_id, error_on_missing=False)
    except Exception:
        logger.warning("Failed to delete bundle blob %s", file_id, exc_info=True)
