"""Shared ingest pathway for custom skill bundles.

Both the custom-skill upload endpoint and the custom external-app create
endpoint take the same uploaded ``.zip`` and run it through the same
validate → parse → hash → store steps. This module is that single pathway;
callers own the DB row they create from the result (a plain ``Skill`` or a
``Skill`` + ``ExternalApp``) and the cleanup of the stored blob on failure.
"""

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
    """Validate, parse, and store a custom skill bundle.

    Derives the slug from the upload filename, validates the zip structure
    (``SKILL.md`` present, no traversal/symlinks, size caps, slug not a reserved
    built-in id), parses ``(name, description)`` from the ``SKILL.md``
    frontmatter, hashes the raw bytes, and saves the blob to the file store.

    Pass ``slug`` to keep an existing row's slug when *replacing* a bundle on an
    update (the slug is the stable skill identity, not derived from the new
    upload's filename). When omitted, the slug comes from ``filename`` — the
    create path.

    Returns the slug, the stored ``bundle_file_id``, the sha256, and the parsed
    ``(name, description)``. The caller owns DB row creation and is responsible
    for deleting ``bundle_file_id`` if its transaction fails.
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
