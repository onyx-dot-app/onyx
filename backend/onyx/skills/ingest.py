import datetime
import io
import math
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, NamedTuple

from onyx.configs.constants import FileOrigin
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.file_store.models import BundleMetadata
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import (
    SKILL_MD_NAME,
    build_single_file_bundle,
    compute_bundle_sha256,
    normalize_custom_bundle,
)
from onyx.skills.metadata import parse_skill_document, parse_skill_md_frontmatter
from onyx.utils.bundle import compute_bundle_metadata
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SkillMdRecord(NamedTuple):
    """The root SKILL.md of a version. `skill_md` is the raw file and is
    authoritative; `frontmatter` is a derived JSON copy. Each is None when
    PostgreSQL cannot store it."""

    name: str | None
    frontmatter: dict[str, Any] | None
    skill_md: str | None

    @property
    def complete(self) -> bool:
        return self.frontmatter is not None and self.skill_md is not None


class _NotJsonStorable(Exception):
    pass


def _storable_text(value: str) -> bool:
    """PostgreSQL text and JSONB reject NUL and unpaired surrogates."""
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _json_value(value: Any) -> Any:
    """Convert YAML 1.1 values to JSONB values; dates become ISO strings."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        try:
            # The JSON writer cannot format ints above Python's digit limit.
            str(value)
        except ValueError as exc:
            raise _NotJsonStorable from exc
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _NotJsonStorable
        return value
    if isinstance(value, str):
        if not _storable_text(value):
            raise _NotJsonStorable
        return value
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        # JSON keys are strings, so 1, true and null keys would collide.
        if not all(isinstance(key, str) and _storable_text(key) for key in value):
            raise _NotJsonStorable
        return {key: _json_value(item) for key, item in value.items()}
    # For example bytes from !!binary, or sets.
    raise _NotJsonStorable


def skill_md_record(
    raw_skill_md: bytes, frontmatter: Mapping[Any, Any] | None
) -> SkillMdRecord:
    try:
        text: str | None = raw_skill_md.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None and not _storable_text(text):
        text = None
    frontmatter_json: dict[str, Any] | None = None
    if frontmatter is not None:
        try:
            frontmatter_json = _json_value(frontmatter)
        except _NotJsonStorable:
            frontmatter_json = None
    name = frontmatter.get("name") if frontmatter is not None else None
    return SkillMdRecord(
        name=(
            name
            if isinstance(name, str) and len(name) <= 64 and _storable_text(name)
            else None
        ),
        frontmatter=frontmatter_json,
        skill_md=text,
    )


def bundle_skill_md_record(bundle_bytes: bytes) -> SkillMdRecord:
    """Raises when the bundle has no root SKILL.md. Invalid frontmatter keeps
    the raw file and leaves `frontmatter` empty."""
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        raw_skill_md = archive.read(SKILL_MD_NAME)
    try:
        frontmatter: dict[Any, Any] | None = parse_skill_md_frontmatter(raw_skill_md)[0]
    except OnyxError:
        frontmatter = None
    return skill_md_record(raw_skill_md, frontmatter)


class IngestedBundle(NamedTuple):
    canonical_name: str
    bundle_file_id: str
    bundle_sha256: str
    description: str
    metadata: BundleMetadata
    skill_md: SkillMdRecord | None = None


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
) -> IngestedBundle:
    """Validate, parse, hash, and store a custom skill bundle.

    Accepts either a ZIP bundle or a standalone ``SKILL.md``. Standalone files
    use their frontmatter ``name`` as canonical identity and are stored as ZIPs.

    Pass ``expected_name`` to keep an existing row's identity when replacing a
    bundle. On creation, both ZIPs and standalone files use the validated
    frontmatter name; the upload filename is not an identity source.

    Prefer ``ingested_skill_bundle`` when the stored blob should be cleaned up
    automatically if the caller's transaction fails.
    """
    is_standalone_skill_md = filename is not None and filename.lower() == "skill.md"
    if is_standalone_skill_md:
        bundle_bytes = build_single_file_bundle(SKILL_MD_NAME, bundle_bytes)

    normalized = normalize_custom_bundle(bundle_bytes)
    with zipfile.ZipFile(io.BytesIO(normalized.content)) as bundle_zip:
        raw_skill_md = bundle_zip.read(SKILL_MD_NAME)
    document = parse_skill_document(
        raw_skill_md,
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
    metadata = compute_bundle_metadata(normalized.content)

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
        metadata=metadata,
        skill_md=skill_md_record(raw_skill_md, document.frontmatter),
    )


@contextmanager
def ingested_skill_bundle(
    bundle_bytes: bytes,
    filename: str | None,
    file_store: FileStore,
    *,
    expected_name: str | None = None,
) -> Iterator[IngestedBundle]:
    ingested = ingest_skill_bundle(
        bundle_bytes,
        filename,
        file_store,
        expected_name=expected_name,
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
