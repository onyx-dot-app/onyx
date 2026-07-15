import io
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import FileStore
from onyx.skills.bundle import build_single_file_bundle
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import parse_skill_md_metadata
from onyx.skills.bundle import SKILL_MD_NAME
from onyx.skills.bundle import slug_from_filename
from onyx.skills.bundle import validate_and_normalize_custom_bundle
from onyx.utils.logger import setup_logger

logger = setup_logger()


class IngestedBundle(NamedTuple):
    slug: str
    bundle_file_id: str
    bundle_sha256: str
    name: str
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
    slug: str | None = None,
) -> IngestedBundle:
    """Validate, parse, hash, and store a custom skill bundle.

    Accepts either a ZIP bundle or a standalone ``SKILL.md``. Standalone files
    use their frontmatter ``name`` as the slug and are stored as canonical ZIPs.

    Pass ``slug`` to keep an existing row's slug when replacing a bundle. On
    creation, ZIPs derive it from their filename and standalone files use the
    frontmatter name.

    Prefer ``ingested_skill_bundle`` when the stored blob should be cleaned up
    automatically if the caller's transaction fails.
    """
    is_standalone_skill_md = filename is not None and filename.lower() == "skill.md"
    metadata: tuple[str, str] | None = None
    if is_standalone_skill_md:
        metadata = parse_skill_md_metadata(bundle_bytes)
        if slug is None:
            slug = metadata[0]
        bundle_bytes = build_single_file_bundle(SKILL_MD_NAME, bundle_bytes)
    else:
        if slug is None:
            slug = slug_from_filename(filename)

    bundle_bytes = validate_and_normalize_custom_bundle(bundle_bytes, slug=slug)
    if metadata is None:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as bundle_zip:
            metadata = parse_skill_md_metadata(bundle_zip.read(SKILL_MD_NAME))
    name, description = metadata
    sha = compute_bundle_sha256(bundle_bytes)

    bundle_file_id = save_skill_bundle_bytes(
        bundle_bytes,
        display_name=f"{slug}.zip",
        file_store=file_store,
    )
    return IngestedBundle(
        slug=slug,
        bundle_file_id=bundle_file_id,
        bundle_sha256=sha,
        name=name,
        description=description,
    )


@contextmanager
def ingested_skill_bundle(
    bundle_bytes: bytes,
    filename: str | None,
    file_store: FileStore,
    *,
    slug: str | None = None,
) -> Iterator[IngestedBundle]:
    ingested = ingest_skill_bundle(
        bundle_bytes,
        filename,
        file_store,
        slug=slug,
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
