"""Custom skill bundle validation and helpers."""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path
from typing import BinaryIO
from typing import Final

import yaml

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import SLUG_REGEX

DEFAULT_PER_FILE_MAX_BYTES: Final[int] = int(
    os.environ.get("SKILL_BUNDLE_PER_FILE_MAX_BYTES") or 25 * 1024 * 1024
)
DEFAULT_TOTAL_MAX_BYTES: Final[int] = int(
    os.environ.get("SKILL_BUNDLE_TOTAL_MAX_BYTES") or 100 * 1024 * 1024
)

SKILL_MD_NAME: Final[str] = "SKILL.md"
TEMPLATE_SUFFIX: Final[str] = ".template"

_FRONTMATTER_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\A---[ \t]*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)

_ZIP_UNIX_CREATE_SYSTEM: Final[int] = 3


def check_slug(slug: str) -> None:
    if not SLUG_REGEX.match(slug):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"invalid slug '{slug}'")


def slug_from_filename(filename: str | None) -> str:
    """Derive a skill slug from the uploaded bundle's filename.

    The bundle ships as ``<slug>.zip`` — strip the extension and validate. We
    don't take basename here: any directory component is suspicious enough
    that we'd rather fail than silently massage the input.
    """
    if not filename:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "bundle upload is missing a filename",
        )
    candidate = filename
    if candidate.lower().endswith(".zip"):
        candidate = candidate[:-4]
    check_slug(candidate)
    return candidate


def read_bundle_file(bundle_file: BinaryIO) -> bytes:
    """Read a bundle stream without buffering an arbitrarily large body."""
    data = bundle_file.read(DEFAULT_TOTAL_MAX_BYTES + 1)
    if len(data) > DEFAULT_TOTAL_MAX_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"Skill bundle exceeds the {DEFAULT_TOTAL_MAX_BYTES} byte limit.",
        )
    return data


def parse_skill_md_metadata(zip_bytes: bytes) -> tuple[str, str]:
    """Extract ``(name, description)`` from the bundle's SKILL.md frontmatter.

    The bundle is the source of truth for skill metadata. ``validate_custom_bundle``
    has already confirmed structural shape; here we re-open the zip just for the
    SKILL.md payload because parsing frontmatter requires the contents, not the
    archive layout.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    with zf:
        try:
            raw = zf.read(SKILL_MD_NAME)
        except KeyError:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "SKILL.md missing at bundle root",
            )

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md must be UTF-8 encoded",
        ) from exc

    match = _FRONTMATTER_REGEX.match(content)
    if match is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md must start with YAML frontmatter delimited by two --- lines",
        )

    try:
        parsed = yaml.safe_load(match.group("frontmatter")) or {}
    except yaml.YAMLError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"SKILL.md frontmatter is not valid YAML: {exc}",
        ) from exc
    if not isinstance(parsed, dict):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter must be a mapping",
        )

    name = parsed.get("name")
    description = parsed.get("description")
    if not isinstance(name, str) or not name.strip():
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter must include a non-empty 'name'",
        )
    if not isinstance(description, str) or not description.strip():
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md frontmatter must include a non-empty 'description'",
        )
    return name.strip(), description.strip()


def strip_skill_md_frontmatter(content: str) -> str:
    match = _FRONTMATTER_REGEX.match(content)
    if match is None:
        return content.strip()
    return content[match.end() :].strip()


def read_custom_bundle_instructions(zip_bytes: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle is not a valid zip.",
        ) from exc

    with zf:
        try:
            raw_skill_md = zf.read(SKILL_MD_NAME)
        except KeyError as exc:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Stored skill bundle is missing SKILL.md.",
            ) from exc

    try:
        skill_md = raw_skill_md.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle SKILL.md must be UTF-8 encoded.",
        ) from exc

    return strip_skill_md_frontmatter(skill_md)


def build_skill_md(
    *,
    name: str,
    description: str,
    instructions_markdown: str,
) -> str:
    name = name.strip()
    description = description.strip()
    instructions_markdown = instructions_markdown.strip()
    if not name:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Skill name cannot be empty.")
    if not description:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Skill description cannot be empty.",
        )
    if not instructions_markdown:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Skill instructions cannot be empty.",
        )

    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{instructions_markdown}\n"


def rewrite_custom_bundle_skill_md(
    zip_bytes: bytes,
    *,
    slug: str,
    name: str,
    description: str,
    instructions_markdown: str,
) -> bytes:
    """Return a new custom bundle with root SKILL.md replaced.

    Existing supporting files are copied through unchanged. The resulting
    archive is validated with the normal custom-bundle validator before it is
    returned to callers for storage.
    """
    new_skill_md = build_skill_md(
        name=name,
        description=description,
        instructions_markdown=instructions_markdown,
    ).encode("utf-8")

    try:
        source_zip = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle is not a valid zip.",
        ) from exc

    output = io.BytesIO()
    saw_skill_md = False
    with (
        source_zip,
        zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as target_zip,
    ):
        for info in source_zip.infolist():
            try:
                normalized = _check_zip_entry_path(info.filename)
            except OnyxError as exc:
                raise OnyxError(
                    OnyxErrorCode.INTERNAL_ERROR,
                    "Stored skill bundle contains an unsafe path.",
                ) from exc
            if _is_symlink(info):
                raise OnyxError(
                    OnyxErrorCode.INTERNAL_ERROR,
                    "Stored skill bundle contains a symlink.",
                )

            if normalized == SKILL_MD_NAME:
                if saw_skill_md:
                    continue
                target_zip.writestr(info, new_skill_md)
                saw_skill_md = True
                continue

            if info.is_dir():
                target_zip.writestr(info, b"")
            else:
                try:
                    target_zip.writestr(info, source_zip.read(info))
                except Exception as exc:
                    raise OnyxError(
                        OnyxErrorCode.INTERNAL_ERROR,
                        "Failed to read stored skill bundle entry.",
                    ) from exc

    if not saw_skill_md:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle is missing SKILL.md.",
        )

    rewritten = output.getvalue()
    validate_custom_bundle(rewritten, slug=slug)
    return rewritten


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
    check_slug(slug)
    if slug in BUILT_IN_SKILLS:
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
