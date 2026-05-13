"""Custom skill bundle validation and helpers.

See docs/craft/features/skills/skills_plan.md §5.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Final

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.registry import BuiltinSkillRegistry

DEFAULT_PER_FILE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
DEFAULT_TOTAL_MAX_BYTES: Final[int] = 100 * 1024 * 1024

SKILL_MD_NAME: Final[str] = "SKILL.md"
TEMPLATE_SUFFIX: Final[str] = ".template"

SLUG_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

_ZIP_UNIX_CREATE_SYSTEM: Final[int] = 3


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
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
) -> None:
    """Validate a custom skill bundle. Returns on success, raises on failure.

    Args:
        zip_bytes: Raw zip bytes uploaded by an admin.
        slug: Caller-supplied slug for this skill.
        per_file_max_bytes: Per-entry uncompressed cap.
        total_max_bytes: Total uncompressed cap.

    Raises:
        OnyxError(INVALID_INPUT): structural violations (bad slug, missing
            SKILL.md, traversal, symlink, template, unreadable entry).
        OnyxError(PAYLOAD_TOO_LARGE): per-file or total size cap exceeded.
    """
    _check_slug(slug)
    if slug in BuiltinSkillRegistry.instance().reserved_slugs():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    with zf:
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

            if normalized == SKILL_MD_NAME:
                saw_skill_md = True

        if not saw_skill_md:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "SKILL.md missing at bundle root",
            )


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

    On any failure mid-extraction (size cap hit, OS error, unsupported
    compression, etc.) the entire ``dest`` directory is removed before the
    error propagates, so the caller never sees a half-populated skill tree.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    _mkdir_or_raise(dest)
    dest_resolved = dest.resolve()

    try:
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
                    _mkdir_or_raise(target)
                    continue
                _mkdir_or_raise(target.parent)
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
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def _mkdir_or_raise(path: Path) -> None:
    """``path.mkdir(parents=True, exist_ok=True)`` with OS errors translated
    to ``OnyxError`` so failed bundle extraction never surfaces as a 500."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"cannot create '{path}': {exc}",
        ) from exc


def compute_bundle_sha256(zip_bytes: bytes) -> str:
    """SHA-256 of the raw upload bytes.

    Hashed over the zip-as-uploaded — two zips with identical contents but
    different timestamps still hash differently. We're detecting "this is the
    exact same upload," not "the contents match."
    """
    return hashlib.sha256(zip_bytes).hexdigest()
