"""Custom skill bundle validation and helpers.

See docs/craft/features/skills/skills_plan.md §5.
"""

from __future__ import annotations

import hashlib
import io
import re
import stat
import zipfile
from pathlib import Path
from typing import Final

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

DEFAULT_PER_FILE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
DEFAULT_TOTAL_MAX_BYTES: Final[int] = 100 * 1024 * 1024

SKILL_MD_NAME: Final[str] = "SKILL.md"
TEMPLATE_SUFFIX: Final[str] = ".template"

SLUG_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

_ZIP_UNIX_CREATE_SYSTEM: Final[int] = 3


class ManifestFileEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size: int


class ManifestMetadata(BaseModel):
    """Bundle-content inventory captured at validation time, persisted as
    JSONB on the ``Skill`` row.

    Only carries bundle facts that the ``Skill`` row itself doesn't already
    have — the file list and total size, for admin-UI surfacing. Frontmatter
    name/description live on the row; admins type them into the upload form
    (with client-side pre-fill via jszip per P4.021).
    """

    model_config = ConfigDict(frozen=True)

    files: list[ManifestFileEntry] = Field(default_factory=list)
    total_uncompressed_bytes: int = 0


def _check_slug(slug: str) -> None:
    if not SLUG_REGEX.match(slug):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"invalid slug '{slug}'")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """True if the zip entry was archived as a Unix symlink.

    We inspect the zip-entry metadata (``external_attr`` mode bits) rather
    than ``Path.is_symlink()`` because at validation time nothing has been
    extracted to disk yet — and the whole point of the check is to refuse
    to extract.
    """
    if info.create_system != _ZIP_UNIX_CREATE_SYSTEM:
        return False
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(unix_mode)


def _check_zip_entry_path(name: str) -> str:
    """Reject path-traversal entries; return a clean relative posix path.

    A zip-bomb-style entry like ``../../etc/passwd`` or ``/etc/passwd`` must
    never reach disk. We refuse to even look at the file contents in that case.
    """
    trimmed = name.rstrip("/")
    if not trimmed:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle entry has empty path: '{name}'",
        )
    if trimmed.startswith("/") or "\\" in trimmed:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle entry escapes root: '{name}'",
        )
    parts = trimmed.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle entry escapes root: '{name}'",
        )
    return trimmed


def validate_custom_bundle(
    zip_bytes: bytes,
    slug: str,
    *,
    reserved_slugs: set[str] | None = None,
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
) -> ManifestMetadata:
    """Validate a custom skill bundle.

    Args:
        zip_bytes: Raw zip bytes uploaded by an admin.
        slug: Caller-supplied slug for this skill.
        reserved_slugs: Slugs registered as built-ins (rejected here). Caller
            threads in ``BuiltinSkillRegistry.instance().reserved_slugs()``;
            we don't call it directly because the registry is a separate
            in-flight task on this stack and we don't want the import edge.
            Consolidate once the registry lands on skills-phase-1.
        per_file_max_bytes: Per-entry uncompressed cap.
        total_max_bytes: Total uncompressed cap.

    Returns:
        ManifestMetadata to persist on the ``Skill`` row.

    Raises:
        OnyxError(INVALID_INPUT): structural violations (bad slug, missing
            SKILL.md, traversal, symlink, template, unreadable entry).
        OnyxError(PAYLOAD_TOO_LARGE): per-file or total size cap exceeded.
    """
    _check_slug(slug)
    if reserved_slugs and slug in reserved_slugs:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    with zf:
        files: list[ManifestFileEntry] = []
        total = 0
        saw_skill_md = False

        for info in zf.infolist():
            if info.is_dir():
                _check_zip_entry_path(info.filename)
                continue

            normalized = _check_zip_entry_path(info.filename)
            if _is_symlink(info):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"bundle contains a symlink: '{normalized}'",
                )
            if normalized.endswith(TEMPLATE_SUFFIX):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "custom skills cannot ship templates",
                )

            size = 0
            try:
                with zf.open(info, mode="r") as fh:
                    while True:
                        chunk = fh.read(64 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > per_file_max_bytes:
                            raise OnyxError(
                                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                                f"file '{normalized}' exceeds "
                                f"{per_file_max_bytes // (1024 * 1024)} MiB",
                            )
                        total += len(chunk)
                        if total > total_max_bytes:
                            raise OnyxError(
                                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                                f"bundle exceeds "
                                f"{total_max_bytes // (1024 * 1024)} MiB uncompressed",
                            )
            except OnyxError:
                raise
            except Exception as exc:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"cannot read '{normalized}': {exc}",
                ) from exc

            files.append(ManifestFileEntry(path=normalized, size=size))
            if normalized == SKILL_MD_NAME:
                saw_skill_md = True

        if not saw_skill_md:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "SKILL.md missing at bundle root",
            )

    return ManifestMetadata(files=files, total_uncompressed_bytes=total)


def _safe_unzip(
    zip_bytes: bytes,
    dest: Path,
    *,
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
) -> None:
    """Defensive unzip into ``dest`` for use at materialization time.

    The validator should have already rejected traversal/symlink/oversized
    bundles at upload, but a validator bug or a tampered blob shouldn't equal
    a sandbox escape or a disk-exhaustion incident. We re-check everything
    here — traversal, symlinks, and the same per-file + total size caps.
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    with zf:
        total = 0
        for info in zf.infolist():
            if _is_symlink(info):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"bundle contains a symlink: '{info.filename}'",
                )
            normalized = _check_zip_entry_path(info.filename)
            target = (dest / normalized).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"bundle entry escapes root: '{info.filename}'",
                )
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            try:
                with zf.open(info, mode="r") as src, open(target, "wb") as out:
                    while True:
                        chunk = src.read(64 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > per_file_max_bytes:
                            raise OnyxError(
                                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                                f"file '{normalized}' exceeds "
                                f"{per_file_max_bytes // (1024 * 1024)} MiB",
                            )
                        total += len(chunk)
                        if total > total_max_bytes:
                            raise OnyxError(
                                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                                f"bundle exceeds "
                                f"{total_max_bytes // (1024 * 1024)} MiB uncompressed",
                            )
                        out.write(chunk)
            except OnyxError:
                raise
            except Exception as exc:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"cannot extract '{normalized}': {exc}",
                ) from exc


def compute_bundle_sha256(zip_bytes: bytes) -> str:
    """SHA-256 of the raw upload bytes.

    Hashed over the zip-as-uploaded — two zips with identical contents but
    different timestamps still hash differently. We're detecting "this is the
    exact same upload," not "the contents match."
    """
    return hashlib.sha256(zip_bytes).hexdigest()
