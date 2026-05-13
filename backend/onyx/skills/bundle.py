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
from typing import Any
from typing import Final

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

VALIDATOR_VERSION: Final[int] = 1

DEFAULT_PER_FILE_MAX_BYTES: Final[int] = 25 * 1024 * 1024
DEFAULT_TOTAL_MAX_BYTES: Final[int] = 100 * 1024 * 1024

SKILL_MD_NAME: Final[str] = "SKILL.md"
TEMPLATE_SUFFIX: Final[str] = ".template"

SLUG_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

_ZIP_UNIX_CREATE_SYSTEM: Final[int] = 3


class InvalidBundleError(OnyxError):
    """Raised when a custom skill bundle fails validation."""

    def __init__(
        self,
        detail: str,
        *,
        error_code: OnyxErrorCode = OnyxErrorCode.INVALID_INPUT,
    ) -> None:
        super().__init__(error_code, detail)


class ManifestFileEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size: int


class ManifestFrontmatter(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None = None
    description: str | None = None


class ManifestMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    frontmatter: ManifestFrontmatter = Field(default_factory=ManifestFrontmatter)
    files: list[ManifestFileEntry] = Field(default_factory=list)
    total_uncompressed_bytes: int = 0
    validator_version: int = VALIDATOR_VERSION


def _check_slug(slug: str) -> None:
    if not SLUG_REGEX.match(slug):
        raise InvalidBundleError(f"invalid slug '{slug}'")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """True if the zip entry was archived as a Unix symlink."""
    if info.create_system != _ZIP_UNIX_CREATE_SYSTEM:
        return False
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(unix_mode)


def _normalize_zip_path(name: str) -> str:
    """Reject path-traversal entries; return a clean relative posix path.

    A zip-bomb-style entry like ``../../etc/passwd`` or ``/etc/passwd`` must
    never reach disk. We refuse to even look at the file contents in that case.
    """
    trimmed = name.rstrip("/")
    if not trimmed:
        raise InvalidBundleError(f"bundle entry has empty path: '{name}'")
    if trimmed.startswith("/") or "\\" in trimmed:
        raise InvalidBundleError(f"bundle entry escapes root: '{name}'")
    parts = trimmed.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise InvalidBundleError(f"bundle entry escapes root: '{name}'")
    return trimmed


def _parse_frontmatter(skill_md_bytes: bytes) -> ManifestFrontmatter:
    """Best-effort YAML frontmatter extraction. Returns empty on any failure."""
    try:
        text = skill_md_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ManifestFrontmatter()

    if not text.startswith("---"):
        return ManifestFrontmatter()

    lines = text.split("\n")
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return ManifestFrontmatter()

    yaml_text = "\n".join(lines[1:end_idx])
    try:
        parsed: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return ManifestFrontmatter()
    if not isinstance(parsed, dict):
        return ManifestFrontmatter()

    name = parsed.get("name")
    description = parsed.get("description")
    return ManifestFrontmatter(
        name=str(name) if name is not None else None,
        description=str(description) if description is not None else None,
    )


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
        reserved_slugs: Slugs registered as built-ins (rejected here).
            Pass ``BuiltinSkillRegistry.instance().reserved_slugs()`` from
            the API layer.
        per_file_max_bytes: Per-entry uncompressed cap.
        total_max_bytes: Total uncompressed cap.

    Returns:
        ManifestMetadata to persist on the ``Skill`` row.

    Raises:
        InvalidBundleError: any rule from spec §5 fails.
    """
    _check_slug(slug)
    if reserved_slugs and slug in reserved_slugs:
        raise InvalidBundleError(f"slug '{slug}' is reserved")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise InvalidBundleError("bundle is not a valid zip")

    with zf:
        files: list[ManifestFileEntry] = []
        total = 0
        skill_md_info: zipfile.ZipInfo | None = None

        for info in zf.infolist():
            if info.is_dir():
                _normalize_zip_path(info.filename)
                continue

            normalized = _normalize_zip_path(info.filename)
            if _is_symlink(info):
                raise InvalidBundleError(f"bundle contains a symlink: '{normalized}'")
            if normalized.endswith(TEMPLATE_SUFFIX):
                raise InvalidBundleError("custom skills cannot ship templates")

            size = 0
            try:
                with zf.open(info, mode="r") as fh:
                    while True:
                        chunk = fh.read(64 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > per_file_max_bytes:
                            raise InvalidBundleError(
                                f"file '{normalized}' exceeds "
                                f"{per_file_max_bytes // (1024 * 1024)} MiB",
                                error_code=OnyxErrorCode.PAYLOAD_TOO_LARGE,
                            )
                        total += len(chunk)
                        if total > total_max_bytes:
                            raise InvalidBundleError(
                                f"bundle exceeds "
                                f"{total_max_bytes // (1024 * 1024)} MiB uncompressed",
                                error_code=OnyxErrorCode.PAYLOAD_TOO_LARGE,
                            )
            except InvalidBundleError:
                raise
            except Exception as exc:
                raise InvalidBundleError(f"cannot read '{normalized}': {exc}") from exc

            files.append(ManifestFileEntry(path=normalized, size=size))
            if normalized == SKILL_MD_NAME:
                skill_md_info = info

        if skill_md_info is None:
            raise InvalidBundleError("SKILL.md missing at bundle root")

        try:
            skill_md_bytes = zf.read(skill_md_info)
        except Exception as exc:
            raise InvalidBundleError(f"cannot read 'SKILL.md': {exc}") from exc
        frontmatter = _parse_frontmatter(skill_md_bytes)

    return ManifestMetadata(
        frontmatter=frontmatter,
        files=files,
        total_uncompressed_bytes=total,
        validator_version=VALIDATOR_VERSION,
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
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise InvalidBundleError("bundle is not a valid zip")

    with zf:
        total = 0
        for info in zf.infolist():
            if _is_symlink(info):
                raise InvalidBundleError(
                    f"bundle contains a symlink: '{info.filename}'"
                )
            normalized = _normalize_zip_path(info.filename)
            target = (dest / normalized).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError:
                raise InvalidBundleError(
                    f"bundle entry escapes root: '{info.filename}'"
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
                            raise InvalidBundleError(
                                f"file '{normalized}' exceeds "
                                f"{per_file_max_bytes // (1024 * 1024)} MiB",
                                error_code=OnyxErrorCode.PAYLOAD_TOO_LARGE,
                            )
                        total += len(chunk)
                        if total > total_max_bytes:
                            raise InvalidBundleError(
                                f"bundle exceeds "
                                f"{total_max_bytes // (1024 * 1024)} MiB uncompressed",
                                error_code=OnyxErrorCode.PAYLOAD_TOO_LARGE,
                            )
                        out.write(chunk)
            except InvalidBundleError:
                raise
            except Exception as exc:
                raise InvalidBundleError(
                    f"cannot extract '{normalized}': {exc}"
                ) from exc


def compute_bundle_sha256(zip_bytes: bytes) -> str:
    """SHA-256 of the raw upload bytes.

    Hashed over the zip-as-uploaded — two zips with identical contents but
    different timestamps still hash differently. We're detecting "this is the
    exact same upload," not "the contents match."
    """
    return hashlib.sha256(zip_bytes).hexdigest()
