"""Custom skill bundle validation and helpers."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import stat
import sys
import zipfile
from collections.abc import Callable, Container, Iterator
from contextlib import ExitStack
from copy import copy
from dataclasses import dataclass
from functools import wraps
from typing import IO, Final, Literal

from onyx.configs.constants import positive_int_from_env
from onyx.db.zip_metadata import DiskPathSet
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.zip_index import IndexedZipInfo, ZipIndex
from onyx.file_processing.zip_limits import ZipMetadataLimitError
from onyx.file_processing.zip_writer import SpooledZipWriter
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.metadata import (
    parse_skill_document,
    parse_skill_md_frontmatter,
    serialize_skill_md,
    split_skill_md,
)
from onyx.skills.models import CustomSkillBundleContents, SkillBundleFile

_MIB: Final[int] = 1024 * 1024


def stored_zip_allowance(total_max_bytes: int, max_file_count: int) -> int:
    """The largest stored ZIP that a bundle within the file limits can need.

    Bundles stored before the ZIP size limit existed can hold up to the
    uncompressed total limit of incompressible files plus ZIP framing."""
    return (
        max(100 * _MIB, total_max_bytes)
        + total_max_bytes // 128
        + max_file_count * 4 * 1024
    )


def zip_metadata_allowance(max_file_count: int) -> int:
    """Central-directory cap for new uploads: 2 KiB per allowed file, at
    least 1 MiB, so a raised file count raises the cap with it."""
    return max(_MIB, max_file_count * 2 * 1024)


_PER_FILE_SETTING = positive_int_from_env("SKILL_BUNDLE_PER_FILE_MAX_BYTES", 25 * _MIB)
_TOTAL_SETTING = positive_int_from_env("SKILL_BUNDLE_TOTAL_MAX_BYTES", 100 * _MIB)
_FILE_COUNT_SETTING = positive_int_from_env("SKILL_BUNDLE_MAX_FILE_COUNT", 500)
_STORED_ZIP_SETTING = positive_int_from_env(
    "SKILL_BUNDLE_STORED_ZIP_MAX_BYTES",
    stored_zip_allowance(_TOTAL_SETTING or 0, _FILE_COUNT_SETTING or 0),
)
_ZIP_SETTING = positive_int_from_env("SKILL_BUNDLE_ZIP_MAX_BYTES", 25 * _MIB)
_INVALID_SETTINGS: Final[tuple[str, ...]] = tuple(
    name
    for name, value in (
        ("SKILL_BUNDLE_PER_FILE_MAX_BYTES", _PER_FILE_SETTING),
        ("SKILL_BUNDLE_TOTAL_MAX_BYTES", _TOTAL_SETTING),
        ("SKILL_BUNDLE_MAX_FILE_COUNT", _FILE_COUNT_SETTING),
        ("SKILL_BUNDLE_STORED_ZIP_MAX_BYTES", _STORED_ZIP_SETTING),
        ("SKILL_BUNDLE_ZIP_MAX_BYTES", _ZIP_SETTING),
    )
    if value is None
)
# Invalid settings disable custom bundles; a zero limit also fails closed.
SKILL_BUNDLE_SETTINGS_ERROR: Final[str | None] = (
    "Custom skill bundles are disabled because "
    f"{', '.join(_INVALID_SETTINGS)} must be a positive integer."
    if _INVALID_SETTINGS
    else None
)
DEFAULT_PER_FILE_MAX_BYTES: Final[int] = _PER_FILE_SETTING or 0
DEFAULT_TOTAL_MAX_BYTES: Final[int] = _TOTAL_SETTING or 0
DEFAULT_STORED_ZIP_MAX_BYTES: Final[int] = _STORED_ZIP_SETTING or 0
DEFAULT_ZIP_MAX_BYTES: Final[int] = min(_ZIP_SETTING or 0, DEFAULT_STORED_ZIP_MAX_BYTES)
DEFAULT_MAX_FILE_COUNT: Final[int] = _FILE_COUNT_SETTING or 0

# New uploads have a central-directory cap that follows the file-count limit.
# Stored bundles have none: ZipIndex reads them in bounded memory.
ZIP_METADATA_MAX_BYTES: Final[int] = zip_metadata_allowance(DEFAULT_MAX_FILE_COUNT)

SkillBundleLimit = Literal[
    "zip_bytes", "zip_metadata_bytes", "file_count", "file_bytes", "total_bytes"
]

SKILL_MD_NAME: Final[str] = "SKILL.md"
TEMPLATE_SUFFIX: Final[str] = ".template"

_ZIP_UNIX_CREATE_SYSTEM: Final[int] = 3
# Common filesystem limits for new writes. Parent directories are tracked per
# level, so depth bounds that work for each path.
_MAX_PATH_BYTES: Final[int] = 4096
_MAX_PATH_SEGMENT_BYTES: Final[int] = 255
_MAX_PATH_DEPTH: Final[int] = 64
# Stored reads skip the path caps; this budget bounds the parent-path set instead.
STORED_PARENT_PATH_MAX_BYTES: Final[int] = 256 * 1024 * 1024

_IGNORED_BUNDLE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {".DS_Store", "Thumbs.db"}
)


@dataclass(frozen=True)
class NormalizedSkillBundle:
    content: bytes
    source_directory: str | None


def assert_skill_bundle_settings_valid() -> None:
    if SKILL_BUNDLE_SETTINGS_ERROR is not None:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE, SKILL_BUNDLE_SETTINGS_ERROR)


def _bundle_limit_error(
    limit: SkillBundleLimit, limit_value: int, detail: str
) -> OnyxError:
    return OnyxError(
        OnyxErrorCode.PAYLOAD_TOO_LARGE,
        detail,
        extra={"limit": limit, "limit_value": limit_value},
    )


def _size_label(max_bytes: int) -> str:
    return (
        f"{max_bytes // (1024 * 1024)} MiB"
        if max_bytes % (1024 * 1024) == 0
        else f"{max_bytes:,} bytes"
    )


def _zip_too_large_error(max_bytes: int) -> OnyxError:
    return _bundle_limit_error(
        "zip_bytes",
        max_bytes,
        f"Skill bundle zip exceeds the {_size_label(max_bytes)} limit.",
    )


def _open_bundle_index(zip_bytes: bytes, max_metadata_bytes: int | None) -> ZipIndex:
    try:
        return ZipIndex(zip_bytes, max_metadata_bytes=max_metadata_bytes)
    except ZipMetadataLimitError as exc:
        limit = max_metadata_bytes or 0
        raise _bundle_limit_error(
            "zip_metadata_bytes",
            limit,
            f"Skill bundle zip file list exceeds the {_size_label(limit)} limit.",
        ) from exc
    except sqlite3.Error as exc:
        raise _temporary_space_error() from exc


def _temporary_space_error() -> OnyxError:
    # ZIP metadata and path sets live in temporary SQLite files; running out of
    # space is not a property of the bundle.
    return OnyxError(
        OnyxErrorCode.SERVICE_UNAVAILABLE,
        "Not enough temporary space to process the skill bundle.",
    )


def _map_temporary_space_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except sqlite3.Error as exc:
            raise _temporary_space_error() from exc

    return wrapper


def _check_rewritten_metadata(content: bytes, *, rewritten: bool, capped: bool) -> None:
    """A rewrite stores names as UTF-8, which can grow a CP437 file list past
    the cap that later edits apply to the saved bundle."""
    if rewritten and capped:
        with _open_bundle_index(content, ZIP_METADATA_MAX_BYTES):
            pass


def _parent_path_bytes(path: str) -> int:
    """UTF-8 bytes the parent-path set stores for one path, without building them."""
    encoded = path.encode("utf-8")
    total = 0
    index = encoded.find(b"/")
    while index >= 0:
        total += index
        index = encoded.find(b"/", index + 1)
    return total


def _parent_paths(path: str) -> Iterator[str]:
    start = 0
    while (index := path.find("/", start)) >= 0:
        yield path[:index]
        start = index + 1


def read_bundle_file(
    bundle_file: IO[bytes],
    *,
    filename: str | None = None,
    max_bytes: int | None = None,
) -> bytes:
    """Read a bundle stream without buffering an arbitrarily large body."""
    assert_skill_bundle_settings_valid()
    is_raw_file = filename is not None and not filename.lower().endswith(".zip")
    if max_bytes is None:
        max_bytes = DEFAULT_PER_FILE_MAX_BYTES if is_raw_file else DEFAULT_ZIP_MAX_BYTES
    data = bundle_file.read(max_bytes + 1)
    if len(data) > max_bytes:
        if is_raw_file:
            raise _bundle_limit_error(
                "file_bytes", max_bytes, f"file '{filename}' exceeds the per-file limit"
            )
        raise _zip_too_large_error(max_bytes)
    return data


def check_stored_zip_size(size: int | None, max_bytes: int) -> None:
    """Reject a stored ZIP from object metadata before downloading it."""
    assert_skill_bundle_settings_valid()
    if size is not None and size > max_bytes:
        raise _zip_too_large_error(max_bytes)


def _check_bundle_file_count(count: int, max_file_count: int | None) -> None:
    if max_file_count is not None and count > max_file_count:
        raise _bundle_limit_error(
            "file_count",
            max_file_count,
            f"bundle contains more than {max_file_count} files",
        )


def strip_skill_md_frontmatter(content: str) -> str:
    try:
        _, instructions_markdown = split_skill_md(content.encode("utf-8"))
    except OnyxError:
        return content.strip()
    return instructions_markdown.strip()


@_map_temporary_space_errors
def _read_stored_bundle(zip_bytes: bytes, files: list[SkillBundleFile] | None) -> str:
    try:
        index = ZipIndex(zip_bytes)
    except zipfile.BadZipFile as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle is not a valid zip.",
        ) from exc

    with index:
        try:
            raw_skill_md = index.read(SKILL_MD_NAME)
        except KeyError as exc:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Stored skill bundle is missing SKILL.md.",
            ) from exc
        for info in index.infos():
            if info.is_dir():
                continue
            normalized = _validated_bundle_path(info, path_limits=False)
            if normalized == SKILL_MD_NAME or _is_ignored_bundle_path(normalized):
                continue
            if files is not None:
                files.append(SkillBundleFile(path=normalized, size=info.file_size))

    try:
        skill_md = raw_skill_md.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle SKILL.md must be UTF-8 encoded.",
        ) from exc
    return strip_skill_md_frontmatter(skill_md)


@_map_temporary_space_errors
def read_bundle_skill_md(zip_bytes: bytes) -> bytes:
    """Read the root SKILL.md of a normalized bundle."""
    with ZipIndex(zip_bytes) as bundle_zip:
        return bundle_zip.read(SKILL_MD_NAME)


def inspect_custom_bundle(zip_bytes: bytes) -> CustomSkillBundleContents:
    """The listing holds each file's path and size; nothing else per entry."""
    files: list[SkillBundleFile] = []
    instructions_markdown = _read_stored_bundle(zip_bytes, files)
    sorted_files = sorted(files, key=lambda entry: entry.path)
    return CustomSkillBundleContents(
        instructions_markdown=instructions_markdown, files=sorted_files
    )


def read_custom_bundle_instructions(zip_bytes: bytes) -> str:
    return _read_stored_bundle(zip_bytes, None)


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


@_map_temporary_space_errors
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
    assert_skill_bundle_settings_valid()
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
        raise _bundle_limit_error(
            "file_bytes",
            DEFAULT_PER_FILE_MAX_BYTES,
            f"file '{SKILL_MD_NAME}' exceeds "
            f"{DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB",
        )

    try:
        source_zip = ZipIndex(zip_bytes)
    except zipfile.BadZipFile as exc:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Stored skill bundle is not a valid zip.",
        ) from exc

    output = io.BytesIO()
    saw_skill_md = False
    with source_zip, SpooledZipWriter(output) as target_zip:
        for info in source_zip.infos():
            try:
                normalized = _validated_bundle_path(info, path_limits=False)
            except OnyxError as exc:
                raise OnyxError(
                    OnyxErrorCode.INTERNAL_ERROR,
                    "Stored skill bundle contains an unsafe path or symlink.",
                ) from exc

            if normalized == SKILL_MD_NAME:
                if saw_skill_md:
                    continue
                try:
                    with source_zip.open(info) as source:
                        original_skill_md = source.read()
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
                    raise _bundle_limit_error(
                        "file_bytes",
                        DEFAULT_PER_FILE_MAX_BYTES,
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
                    with source_zip.open(info) as source:
                        target_zip.writestr(info, source.read())
                except sqlite3.Error:
                    raise
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
    # Every entry except the new SKILL.md is copied unchanged from storage.
    return normalize_custom_bundle(rewritten, uncapped_paths=EVERY_PATH).content


def _validated_bundle_path(info: zipfile.ZipInfo, *, path_limits: bool = True) -> str:
    """Return the normalized bundle path, rejecting traversal and symlinks.

    ``path_limits`` applies the length and depth caps; stored reads skip them."""
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
    if path_limits and (
        len(trimmed.encode()) > _MAX_PATH_BYTES
        or len(parts) > _MAX_PATH_DEPTH
        or any(len(p.encode()) > _MAX_PATH_SEGMENT_BYTES for p in parts)
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle entry path is too long or too deep: '{trimmed[:200]}'",
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


@dataclass
class _BundleShape:
    """What the wrapper checks need, gathered one file at a time."""

    file_count: int = 0
    has_ignored: bool = False
    has_root_skill_md: bool = False
    all_nested: bool = True
    # At most two distinct values: callers only ask whether there is one.
    roots: set[str] | None = None
    wrapped_skill_md: list[str] | None = None

    def add(self, path: str) -> None:
        self.file_count += 1
        if _is_ignored_bundle_path(path):
            self.has_ignored = True
            return
        root, slash, rest = path.partition("/")
        self.has_root_skill_md |= path == SKILL_MD_NAME
        self.all_nested &= bool(slash)
        self.roots = _add_capped(self.roots, root)
        if rest == SKILL_MD_NAME:
            wrapped = self.wrapped_skill_md or []
            self.wrapped_skill_md = (wrapped + [path])[:2]

    def wrapper_prefix(self) -> str | None:
        """Identify an optional single directory wrapped around a skill bundle."""
        roots = self.roots or set()
        if self.has_root_skill_md:
            return None
        wrapped = self.wrapped_skill_md or []
        if len(wrapped) != 1:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "SKILL.md missing at bundle root or directly inside one "
                "top-level directory",
            )
        wrapper_prefix = wrapped[0].split("/", maxsplit=1)[0]
        if not self.all_nested or roots != {wrapper_prefix}:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "bundle contains files outside the directory containing SKILL.md",
            )
        return wrapper_prefix


def _add_capped(values: set[str] | None, value: str) -> set[str]:
    values = values or set()
    if len(values) < 2:
        values.add(value)
    return values


def _copy_validated_bundle_file(
    *,
    source_zip: ZipIndex,
    source_info: IndexedZipInfo,
    source_path: str,
    output_path: str,
    target_zip: SpooledZipWriter | None,
    per_file_max_bytes: int,
    total_bytes_before_file: int,
    total_max_bytes: int,
) -> int:
    target: IO[bytes] | io.BufferedIOBase | None = None
    size = 0
    try:
        with source_zip.open(source_info) as source:
            if target_zip is not None:
                target_info = copy(source_info)
                target_info.filename = output_path
                # A Unicode-path extra field could override the renamed path.
                target_info.extra = b""
                target_info.comment = b""
                target_info.compress_type = zipfile.ZIP_DEFLATED
                target = target_zip.open(target_info, mode="w")

            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > per_file_max_bytes:
                    raise _bundle_limit_error(
                        "file_bytes",
                        per_file_max_bytes,
                        f"file '{output_path}' exceeds "
                        f"{per_file_max_bytes // (1024 * 1024)} MiB",
                    )
                if total_bytes_before_file + size > total_max_bytes:
                    raise _bundle_limit_error(
                        "total_bytes",
                        total_max_bytes,
                        f"bundle exceeds "
                        f"{total_max_bytes // (1024 * 1024)} MiB uncompressed",
                    )
                if target is not None:
                    target.write(chunk)
    except (OnyxError, sqlite3.Error):
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
            except sqlite3.Error:
                if active_exception is None:
                    raise
            except Exception as exc:
                if active_exception is None:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        f"cannot write normalized bundle entry '{output_path}': {exc}",
                    ) from exc
    return size


class _EveryPath:
    """Container holding every path: all entries come unchanged from storage."""

    def __contains__(self, path: object) -> bool:
        return True


# For bundles that an edit function already checked: the edit applied the caps
# to the paths it added, and the other paths come unchanged from storage.
EVERY_PATH: Final[Container[str]] = _EveryPath()


@dataclass(frozen=True)
class _PathCaps:
    """Which entries the length and depth caps apply to.

    A stored read skips them for every entry. An edit skips them for
    ``uncapped_paths``, the stored paths it keeps unchanged, so a legacy path
    over the caps does not block edits elsewhere in the bundle."""

    stored_read: bool = False
    uncapped_paths: Container[str] | None = None

    @property
    def parent_path_budget(self) -> bool:
        return self.stored_read or self.uncapped_paths is not None

    def path(self, info: zipfile.ZipInfo) -> str:
        if self.stored_read:
            return _validated_bundle_path(info, path_limits=False)
        if self.uncapped_paths is None:
            return _validated_bundle_path(info)
        path = _validated_bundle_path(info, path_limits=False)
        if path not in self.uncapped_paths:
            _validated_bundle_path(info)
        return path


def _add_output_directories(
    source_zip: ZipIndex,
    wrapper_prefix: str | None,
    output_directories: DiskPathSet,
    *,
    caps: _PathCaps,
) -> None:
    for info in source_zip.infos():
        normalized = caps.path(info)
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

        output_directories.add(output_directory_path)
        for parent_path in _parent_paths(output_directory_path):
            output_directories.add(parent_path)


def _add_output_path(
    output_path: str, output_paths: DiskPathSet, output_directories: DiskPathSet
) -> None:
    if output_path in output_paths:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle contains duplicate path '{output_path}'",
        )
    if output_path in output_directories or any(
        parent_path in output_paths for parent_path in _parent_paths(output_path)
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"bundle contains conflicting path '{output_path}'",
        )
    output_paths.add(output_path)
    for parent_path in _parent_paths(output_path):
        output_directories.add(parent_path)


def normalize_custom_bundle(
    zip_bytes: bytes,
    *,
    zip_max_bytes: int | None = DEFAULT_ZIP_MAX_BYTES,
    max_file_count: int | None = DEFAULT_MAX_FILE_COUNT,
    per_file_max_bytes: int = DEFAULT_PER_FILE_MAX_BYTES,
    total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES,
    stored_read: bool = False,
    uncapped_paths: Container[str] | None = None,
) -> NormalizedSkillBundle:
    """Validate a custom bundle and remove one optional wrapper directory.

    Stored custom bundles always use a canonical root-level ``SKILL.md`` layout.
    A common ``zip -r skill.zip skill`` archive is accepted at ingestion and
    flattened here before metadata parsing, hashing, and storage.

    Each limit is checked on its own and the first one that fails raises a
    413. ``None`` skips the zip size or file count check; reads of bundles
    stored before those limits existed use it, and then the central directory
    has no size cap either. Path sets live in SQLite, so memory does not grow
    with the number of entries.

    ``stored_read`` reads a bundle that is already saved: path length and depth
    caps do not apply, and a parent-path byte budget bounds the path sets.
    ``uncapped_paths`` are stored paths that an edit keeps unchanged; the caps
    apply only to the other paths, and the parent-path budget applies too.
    """
    caps = _PathCaps(stored_read=stored_read, uncapped_paths=uncapped_paths)
    assert_skill_bundle_settings_valid()
    if zip_max_bytes is not None and len(zip_bytes) > zip_max_bytes:
        raise _zip_too_large_error(zip_max_bytes)
    try:
        source_zip = _open_bundle_index(
            zip_bytes,
            None if max_file_count is None else zip_metadata_allowance(max_file_count),
        )
    except zipfile.BadZipFile:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "bundle is not a valid zip")

    output = io.BytesIO()
    try:
        with (
            source_zip,
            DiskPathSet() as output_paths,
            DiskPathSet() as output_directories,
        ):
            shape = _BundleShape()
            parent_path_bytes = 0
            for info in source_zip.infos():
                normalized = caps.path(info)
                if not info.is_dir():
                    shape.add(normalized)
                if caps.parent_path_budget:
                    parent_path_bytes += _parent_path_bytes(normalized)
                    if parent_path_bytes > STORED_PARENT_PATH_MAX_BYTES:
                        raise _bundle_limit_error(
                            "zip_metadata_bytes",
                            STORED_PARENT_PATH_MAX_BYTES,
                            "Stored skill bundle folder paths exceed the read limit.",
                        )
            _check_bundle_file_count(shape.file_count, max_file_count)
            wrapper_prefix = shape.wrapper_prefix()
            needs_rewrite = wrapper_prefix is not None or shape.has_ignored

            _add_output_directories(
                source_zip,
                wrapper_prefix,
                output_directories,
                caps=caps,
            )
            target_zip = SpooledZipWriter(output) if needs_rewrite else None
            total = 0
            saw_skill_md = False
            try:
                for info in source_zip.infos():
                    normalized = caps.path(info)
                    if info.is_dir() or _is_ignored_bundle_path(normalized):
                        continue

                    output_path = normalized
                    if wrapper_prefix is not None:
                        output_path = normalized.removeprefix(f"{wrapper_prefix}/")

                    _add_output_path(output_path, output_paths, output_directories)

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
                    except sqlite3.Error:
                        if active_exception is None:
                            raise
                    except Exception as exc:
                        if active_exception is None:
                            raise OnyxError(
                                OnyxErrorCode.INVALID_INPUT,
                                f"cannot finish normalized bundle: {exc}",
                            ) from exc
    except sqlite3.Error as exc:
        raise _temporary_space_error() from exc

    if not saw_skill_md:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "SKILL.md missing at bundle root or directly inside one "
            "top-level directory",
        )
    content = output.getvalue() if needs_rewrite else zip_bytes
    if zip_max_bytes is not None and len(content) > zip_max_bytes:
        raise _zip_too_large_error(zip_max_bytes)
    _check_rewritten_metadata(
        content, rewritten=needs_rewrite, capped=max_file_count is not None
    )
    return NormalizedSkillBundle(content=content, source_directory=wrapper_prefix)


@_map_temporary_space_errors
def update_custom_bundle_files(
    existing_zip_bytes: bytes | Callable[[], bytes],
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
    A callable for ``existing_zip_bytes`` is read only when the existing bundle
    is needed, so a full replacement does not depend on it.
    """
    assert_skill_bundle_settings_valid()
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
        upload_zip: ZipIndex | None = None
        changed_paths: set[str]
        if upload_bytes is not None:
            assert filename is not None
            if (
                filename.lower().endswith(".zip")
                and len(upload_bytes) > DEFAULT_ZIP_MAX_BYTES
            ):
                raise _zip_too_large_error(DEFAULT_ZIP_MAX_BYTES)
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
                    _open_bundle_index(upload_archive_bytes, ZIP_METADATA_MAX_BYTES)
                )
            except zipfile.BadZipFile as exc:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT, "upload is not a valid zip"
                ) from exc

            # The metadata cap bounds this list of upload paths.
            upload_infos = [
                (info.is_dir(), _validated_bundle_path(info))
                for info in upload_zip.infos()
            ]
            _check_bundle_file_count(
                sum(not is_dir for is_dir, _ in upload_infos),
                DEFAULT_MAX_FILE_COUNT,
            )
            upload_file_paths = [
                path
                for is_dir, path in upload_infos
                if not is_dir and not _is_ignored_bundle_path(path)
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
            # A stored path over the caps must stay removable.
            normalized_remove_path = _validated_bundle_path(
                zipfile.ZipInfo(remove_path), path_limits=False
            )
            if normalized_remove_path == SKILL_MD_NAME:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT, "SKILL.md cannot be removed"
                )
            changed_paths = {normalized_remove_path}

        existing_bytes = (
            existing_zip_bytes
            if isinstance(existing_zip_bytes, bytes)
            else existing_zip_bytes()
        )
        try:
            existing_zip = archives.enter_context(ZipIndex(existing_bytes))
        except zipfile.BadZipFile as exc:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Stored skill bundle is not a valid zip.",
            ) from exc

        found_remove_path = False
        for info in existing_zip.infos():
            path = _validated_bundle_path(info, path_limits=False)
            found_remove_path |= not info.is_dir() and path in changed_paths
        if remove_path is not None and not found_remove_path:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill file not found")

        kept_paths = archives.enter_context(DiskPathSet())
        total = 0
        with SpooledZipWriter(output) as target_zip:
            sources = [existing_zip]
            if upload_zip is not None:
                sources.append(upload_zip)
            for source_zip in sources:
                for info in source_zip.infos():
                    # The final normalization applies the write caps.
                    path = _validated_bundle_path(
                        info, path_limits=source_zip is not existing_zip
                    )
                    if source_zip is existing_zip and path in changed_paths:
                        continue
                    if info.is_dir() or _is_ignored_bundle_path(path):
                        continue
                    if source_zip is existing_zip:
                        kept_paths.add(path)
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
            uncapped_paths=kept_paths,
        ).content


def compute_bundle_sha256(zip_bytes: bytes) -> str:
    """SHA-256 of the bundle bytes supplied by the caller.

    Ingestion normalizes wrapped bundles before calling this helper so the hash
    always describes the bytes stored in the file store. Two canonical zips
    with identical contents but different timestamps still hash differently.
    """
    return hashlib.sha256(zip_bytes).hexdigest()
