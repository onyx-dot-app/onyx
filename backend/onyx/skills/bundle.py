"""Custom skill bundle validation and helpers."""

from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import sys
import zipfile
from copy import copy
from typing import BinaryIO
from typing import Final
from typing import IO

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

_IGNORED_BUNDLE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {".DS_Store", "Thumbs.db"}
)


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

    The bundle is the source of truth for skill metadata.
    ``validate_and_normalize_custom_bundle`` has already confirmed structural
    shape; here we re-open the zip just for the SKILL.md payload because parsing
    frontmatter requires the contents, not the archive layout.
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
    check_slug(slug)
    if slug in BUILT_IN_SKILLS:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")

    new_skill_md = build_skill_md(
        name=name,
        description=description,
        instructions_markdown=instructions_markdown,
    ).encode("utf-8")
    if len(new_skill_md) > DEFAULT_PER_FILE_MAX_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"file '{SKILL_MD_NAME}' exceeds "
            f"{DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB",
        )

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
                normalized = _validated_bundle_path(info)
            except OnyxError as exc:
                raise OnyxError(
                    OnyxErrorCode.INTERNAL_ERROR,
                    "Stored skill bundle contains an unsafe path or symlink.",
                ) from exc

            if normalized == SKILL_MD_NAME:
                if saw_skill_md:
                    continue
                fresh_info = zipfile.ZipInfo(filename=SKILL_MD_NAME)
                fresh_info.compress_type = zipfile.ZIP_DEFLATED
                target_zip.writestr(fresh_info, new_skill_md)
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
    return validate_and_normalize_custom_bundle(rewritten, slug=slug)


def _validated_bundle_path(info: zipfile.ZipInfo) -> str:
    """Return the normalized bundle path, rejecting traversal and symlinks."""
    name = info.filename
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
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    if info.create_system == _ZIP_UNIX_CREATE_SYSTEM and stat.S_ISLNK(unix_mode):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle contains a symlink: '{trimmed}'",
        )
    return trimmed


def _is_ignored_bundle_path(path: str) -> bool:
    parts = path.split("/")
    basename = parts[-1]
    return (
        parts[0] == "__MACOSX"
        or basename in _IGNORED_BUNDLE_FILE_NAMES
        or basename.startswith("._")
    )


def _bundle_wrapper_prefix(file_paths: list[str]) -> str | None:
    """Identify an optional single directory wrapped around a skill bundle."""
    meaningful_paths = [
        path for path in file_paths if not _is_ignored_bundle_path(path)
    ]
    if SKILL_MD_NAME in meaningful_paths:
        return None

    wrapped_skill_md_paths = [
        path
        for path in meaningful_paths
        if len(path.split("/")) == 2 and path.endswith(f"/{SKILL_MD_NAME}")
    ]
    if len(wrapped_skill_md_paths) != 1:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md missing at bundle root or directly inside one "
            "top-level directory",
        )

    wrapper_prefix = wrapped_skill_md_paths[0].split("/", maxsplit=1)[0]
    unexpected_paths = [
        path for path in meaningful_paths if not path.startswith(f"{wrapper_prefix}/")
    ]
    if unexpected_paths:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "bundle contains files outside the directory containing SKILL.md",
        )
    return wrapper_prefix


def _copy_validated_bundle_file(
    *,
    source_zip: zipfile.ZipFile,
    source_info: zipfile.ZipInfo,
    source_path: str,
    output_path: str,
    target_zip: zipfile.ZipFile | None,
    per_file_max_bytes: int,
    total_bytes_before_file: int,
    total_max_bytes: int,
) -> int:
    target: IO[bytes] | None = None
    size = 0
    try:
        with source_zip.open(source_info, mode="r") as source:
            if target_zip is not None:
                target_info = copy(source_info)
                target_info.filename = output_path
                target_info.orig_filename = output_path
                target_info.compress_type = zipfile.ZIP_DEFLATED
                target = target_zip.open(target_info, mode="w")

            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > per_file_max_bytes:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"file '{output_path}' exceeds "
                        f"{per_file_max_bytes // (1024 * 1024)} MiB",
                    )
                if total_bytes_before_file + size > total_max_bytes:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"bundle exceeds "
                        f"{total_max_bytes // (1024 * 1024)} MiB uncompressed",
                    )
                if target is not None:
                    target.write(chunk)
    except OnyxError:
        raise
    except Exception as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"cannot read '{source_path}': {exc}",
        ) from exc
    finally:
        if target is not None:
            active_exception = sys.exception()
            try:
                target.close()
            except Exception as exc:
                if active_exception is None:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"cannot write normalized bundle entry '{output_path}': {exc}",
                    ) from exc
    return size


def validate_and_normalize_custom_bundle(
    zip_bytes: bytes,
    slug: str,
    *,
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
) -> bytes:
    """Validate a custom bundle and remove one optional wrapper directory.

    Stored custom bundles always use a canonical root-level ``SKILL.md`` layout.
    A common ``zip -r skill.zip skill`` archive is accepted at ingestion and
    flattened here before metadata parsing, hashing, and storage.
    """
    check_slug(slug)
    if slug in BUILT_IN_SKILLS:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")

    try:
        source_zip = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    with source_zip:
        normalized_infos = [
            (info, _validated_bundle_path(info)) for info in source_zip.infolist()
        ]
        file_paths = [
            normalized for info, normalized in normalized_infos if not info.is_dir()
        ]
        wrapper_prefix = _bundle_wrapper_prefix(file_paths)
        needs_rewrite = wrapper_prefix is not None or any(
            _is_ignored_bundle_path(path) for path in file_paths
        )

        output = io.BytesIO()
        target_zip = (
            zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED)
            if needs_rewrite
            else None
        )
        total = 0
        output_paths: set[str] = set()
        output_directory_paths: set[str] = set()
        saw_skill_md = False

        try:
            for info, normalized in normalized_infos:
                if info.is_dir() or _is_ignored_bundle_path(normalized):
                    continue

                output_path = normalized
                if wrapper_prefix is not None:
                    output_path = normalized.removeprefix(f"{wrapper_prefix}/")

                if output_path in output_paths:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"bundle contains duplicate path '{output_path}'",
                    )
                path_parts = output_path.split("/")
                parent_paths = {
                    "/".join(path_parts[:index]) for index in range(1, len(path_parts))
                }
                if output_path in output_directory_paths or output_paths.intersection(
                    parent_paths
                ):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"bundle contains conflicting path '{output_path}'",
                    )
                output_paths.add(output_path)
                output_directory_paths.update(parent_paths)

                if output_path.endswith(TEMPLATE_SUFFIX):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "custom skills cannot ship templates",
                    )

                total += _copy_validated_bundle_file(
                    source_zip=source_zip,
                    source_info=info,
                    source_path=normalized,
                    output_path=output_path,
                    target_zip=target_zip,
                    per_file_max_bytes=per_file_max_bytes,
                    total_bytes_before_file=total,
                    total_max_bytes=total_max_bytes,
                )

                if output_path == SKILL_MD_NAME:
                    saw_skill_md = True
        finally:
            if target_zip is not None:
                active_exception = sys.exception()
                try:
                    target_zip.close()
                except Exception as exc:
                    if active_exception is None:
                        raise OnyxError(
                            OnyxErrorCode.INVALID_INPUT,
                            f"cannot finish normalized bundle: {exc}",
                        ) from exc

    if not saw_skill_md:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md missing at bundle root or directly inside one "
            "top-level directory",
        )
    return output.getvalue() if needs_rewrite else zip_bytes


def compute_bundle_sha256(zip_bytes: bytes) -> str:
    """SHA-256 of the bundle bytes supplied by the caller.

    Ingestion normalizes wrapped bundles before calling this helper so the hash
    always describes the bytes stored in the file store. Two canonical zips
    with identical contents but different timestamps still hash differently.
    """
    return hashlib.sha256(zip_bytes).hexdigest()
