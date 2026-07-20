"""Custom skill bundle validation and helpers."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import sys
import zipfile
from contextlib import ExitStack
from copy import copy
from dataclasses import dataclass
from typing import IO, Final

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.metadata import (
    parse_skill_document,
    parse_skill_md_frontmatter,
    serialize_skill_md,
    split_skill_md,
)
from onyx.skills.models import CustomSkillBundleContents, SkillBundleFile

DEFAULT_PER_FILE_MAX_BYTES: Final[int] = int(
    os.environ.get("SKILL_BUNDLE_PER_FILE_MAX_BYTES") or 25 * 1024 * 1024
)
DEFAULT_TOTAL_MAX_BYTES: Final[int] = int(
    os.environ.get("SKILL_BUNDLE_TOTAL_MAX_BYTES") or 100 * 1024 * 1024
)

SKILL_MD_NAME: Final[str] = "SKILL.md"
TEMPLATE_SUFFIX: Final[str] = ".template"

_ZIP_UNIX_CREATE_SYSTEM: Final[int] = 3

_IGNORED_BUNDLE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {".DS_Store", "Thumbs.db"}
)


@dataclass(frozen=True)
class NormalizedSkillBundle:
    content: bytes
    source_directory: str | None


def read_bundle_file(bundle_file: IO[bytes]) -> bytes:
    """Read a bundle stream without buffering an arbitrarily large body."""
    data = bundle_file.read(DEFAULT_TOTAL_MAX_BYTES + 1)
    if len(data) > DEFAULT_TOTAL_MAX_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"Skill bundle exceeds the {DEFAULT_TOTAL_MAX_BYTES} byte limit.",
        )
    return data


def strip_skill_md_frontmatter(content: str) -> str:
    try:
        _, instructions_markdown = split_skill_md(content.encode("utf-8"))
    except OnyxError:
        return content.strip()
    return instructions_markdown.strip()


def inspect_custom_bundle(zip_bytes: bytes) -> CustomSkillBundleContents:
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
        files: list[SkillBundleFile] = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            normalized = _validated_bundle_path(info)
            if normalized == SKILL_MD_NAME or _is_ignored_bundle_path(normalized):
                continue
            files.append(SkillBundleFile(path=normalized, size=info.file_size))

    try:
        skill_md = raw_skill_md.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle SKILL.md must be UTF-8 encoded.",
        ) from exc

    return CustomSkillBundleContents(
        instructions_markdown=strip_skill_md_frontmatter(skill_md),
        files=sorted(files, key=lambda entry: entry.path),
    )


def read_custom_bundle_instructions(zip_bytes: bytes) -> str:
    return inspect_custom_bundle(zip_bytes).instructions_markdown


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

    skill_md = serialize_skill_md(
        {"name": name, "description": description},
        instructions_markdown,
    )
    parse_skill_document(skill_md.encode("utf-8"))
    return skill_md


def build_single_file_bundle(filename: str, content: bytes) -> bytes:
    info = zipfile.ZipInfo(filename=filename)
    _validated_bundle_path(info)
    info.compress_type = zipfile.ZIP_DEFLATED
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(info, content)
    return output.getvalue()


def rewrite_custom_bundle_skill_md(
    zip_bytes: bytes,
    *,
    canonical_name: str,
    description: str,
    instructions_markdown: str,
) -> bytes:
    """Return a new custom bundle with root SKILL.md replaced.

    Existing supporting files and optional frontmatter metadata are copied
    through unchanged. The resulting archive is structurally normalized before
    it is returned to callers for storage.
    """
    if canonical_name in BUILT_IN_SKILLS:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"skill name '{canonical_name}' is reserved",
        )
    base_skill_md = build_skill_md(
        name=canonical_name,
        description=description,
        instructions_markdown=instructions_markdown,
    ).encode("utf-8")
    if len(base_skill_md) > DEFAULT_PER_FILE_MAX_BYTES:
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
                try:
                    original_skill_md = source_zip.read(info)
                except Exception as exc:
                    raise OnyxError(
                        OnyxErrorCode.INTERNAL_ERROR,
                        "Failed to read stored skill bundle entry.",
                    ) from exc
                frontmatter, _ = parse_skill_md_frontmatter(original_skill_md)
                frontmatter["name"] = canonical_name
                frontmatter["description"] = description
                new_skill_md = serialize_skill_md(
                    frontmatter,
                    instructions_markdown,
                ).encode("utf-8")
                if len(new_skill_md) > DEFAULT_PER_FILE_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"file '{SKILL_MD_NAME}' exceeds "
                        f"{DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB",
                    )
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
    return normalize_custom_bundle(rewritten).content


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


def normalize_custom_bundle(
    zip_bytes: bytes,
    *,
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
) -> NormalizedSkillBundle:
    """Validate a custom bundle and remove one optional wrapper directory.

    Stored custom bundles always use a canonical root-level ``SKILL.md`` layout.
    A common ``zip -r skill.zip skill`` archive is accepted at ingestion and
    flattened here before metadata parsing, hashing, and storage.
    """
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

        for info, normalized in normalized_infos:
            if not info.is_dir() or _is_ignored_bundle_path(normalized):
                continue

            output_directory_path = normalized
            if wrapper_prefix is not None:
                if normalized == wrapper_prefix:
                    continue
                wrapper_path_prefix = f"{wrapper_prefix}/"
                if not normalized.startswith(wrapper_path_prefix):
                    continue
                output_directory_path = normalized.removeprefix(wrapper_path_prefix)

            directory_parts = output_directory_path.split("/")
            output_directory_paths.add(output_directory_path)
            output_directory_paths.update(
                "/".join(directory_parts[:index])
                for index in range(1, len(directory_parts))
            )

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
    return NormalizedSkillBundle(
        content=output.getvalue() if needs_rewrite else zip_bytes,
        source_directory=wrapper_prefix,
    )


def update_custom_bundle_files(
    existing_zip_bytes: bytes,
    upload_bytes: bytes | None = None,
    *,
    filename: str | None = None,
    remove_path: str | None = None,
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
) -> bytes:
    """Apply an upload or file removal to a custom skill bundle.

    A ZIP or standalone file containing ``SKILL.md`` is a full bundle
    replacement. Other uploads are merged into the existing bundle, replacing
    files at matching paths while preserving ``SKILL.md`` and unrelated files.
    """
    is_upload = upload_bytes is not None
    if is_upload == (remove_path is not None):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "provide exactly one file upload or path to remove",
        )
    if is_upload and not filename:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "upload is missing a filename")

    output = io.BytesIO()
    with ExitStack() as archives:
        upload_zip: zipfile.ZipFile | None = None
        upload_infos: list[tuple[zipfile.ZipInfo, str]] = []
        changed_paths: set[str]
        if upload_bytes is not None:
            assert filename is not None
            upload_archive_bytes = (
                upload_bytes
                if filename.lower().endswith(".zip")
                else build_single_file_bundle(
                    SKILL_MD_NAME
                    if filename.lower() == SKILL_MD_NAME.lower()
                    else filename,
                    upload_bytes,
                )
            )
            try:
                upload_zip = archives.enter_context(
                    zipfile.ZipFile(io.BytesIO(upload_archive_bytes))
                )
            except zipfile.BadZipFile as exc:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT, "upload is not a valid zip"
                ) from exc

            upload_infos = [
                (info, _validated_bundle_path(info)) for info in upload_zip.infolist()
            ]
            upload_file_paths = [
                path
                for info, path in upload_infos
                if not info.is_dir() and not _is_ignored_bundle_path(path)
            ]
            if any(
                path.split("/")[-1].lower() == SKILL_MD_NAME.lower()
                for path in upload_file_paths
            ):
                return normalize_custom_bundle(
                    upload_archive_bytes,
                    per_file_max_bytes=per_file_max_bytes,
                    total_max_bytes=total_max_bytes,
                ).content
            if not upload_file_paths:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, "upload contains no files")
            if len(upload_file_paths) != len(set(upload_file_paths)):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT, "upload contains duplicate paths"
                )
            if any(path.endswith(TEMPLATE_SUFFIX) for path in upload_file_paths):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "custom skills cannot ship templates",
                )
            changed_paths = set(upload_file_paths)
        else:
            assert remove_path is not None
            normalized_remove_path = _validated_bundle_path(
                zipfile.ZipInfo(remove_path)
            )
            if normalized_remove_path == SKILL_MD_NAME:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT, "SKILL.md cannot be removed"
                )
            changed_paths = {normalized_remove_path}

        try:
            existing_zip = archives.enter_context(
                zipfile.ZipFile(io.BytesIO(existing_zip_bytes))
            )
        except zipfile.BadZipFile as exc:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Stored skill bundle is not a valid zip.",
            ) from exc

        existing_infos = [
            (info, _validated_bundle_path(info)) for info in existing_zip.infolist()
        ]
        if remove_path is not None and not any(
            not info.is_dir() and path in changed_paths for info, path in existing_infos
        ):
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill file not found")

        total = 0
        with zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as target_zip:
            sources = [(existing_zip, existing_infos)]
            if upload_zip is not None:
                sources.append((upload_zip, upload_infos))
            for source_zip, source_infos in sources:
                for info, path in source_infos:
                    if source_zip is existing_zip and path in changed_paths:
                        continue
                    if info.is_dir() or _is_ignored_bundle_path(path):
                        continue
                    total += _copy_validated_bundle_file(
                        source_zip=source_zip,
                        source_info=info,
                        source_path=path,
                        output_path=path,
                        target_zip=target_zip,
                        per_file_max_bytes=per_file_max_bytes,
                        total_bytes_before_file=total,
                        total_max_bytes=total_max_bytes,
                    )

    return normalize_custom_bundle(
        output.getvalue(),
        per_file_max_bytes=per_file_max_bytes,
        total_max_bytes=total_max_bytes,
    ).content


def compute_bundle_sha256(zip_bytes: bytes) -> str:
    """SHA-256 of the bundle bytes supplied by the caller.

    Ingestion normalizes wrapped bundles before calling this helper so the hash
    always describes the bytes stored in the file store. Two canonical zips
    with identical contents but different timestamps still hash differently.
    """
    return hashlib.sha256(zip_bytes).hexdigest()
