"""Skill bundle ZIP metadata: a cap for new uploads, bounded reads for stored ones."""

from __future__ import annotations

import io
import sqlite3
import struct
import tracemalloc
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.db import skill_version
from onyx.db.models import Skill, SkillVersion
from onyx.db.zip_metadata import DiskPathSet, SpooledZipInfos
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import BundleMetadata
from onyx.skills import push
from onyx.skills.bundle import (
    STORED_BUNDLE_LIMITS,
    STORED_PARENT_PATH_MAX_BYTES,
    ZIP_METADATA_MAX_BYTES,
    _parent_path_bytes,
    inspect_custom_bundle,
    normalize_custom_bundle,
    read_custom_bundle_instructions,
    rewrite_custom_bundle_skill_md,
    update_custom_bundle_files,
)
from onyx.skills.validation import load_stored_custom_skill_bundle
from onyx.utils.bundle import compute_bundle_metadata
from tests.unit.onyx.file_processing.test_zip_index import (
    directory_size,
    raw_zip,
    with_zip64_end,
)

_SKILL_MD = b"---\nname: limits\ndescription: Limit checks\n---\n\nBody\n"
_MIB = 1024 * 1024


def test_paths_close_sqlite_when_schema_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect("")
    failed = MagicMock(wraps=connection)
    failed.execute.side_effect = sqlite3.OperationalError("schema failure")
    monkeypatch.setattr(sqlite3, "connect", lambda _: failed)
    try:
        with pytest.raises(sqlite3.OperationalError, match="schema failure"):
            DiskPathSet()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    finally:
        connection.close()


def _bundle(
    names: list[str], skill_md: str = "SKILL.md", **options: int | bool
) -> bytes:
    entries = [(skill_md, _SKILL_MD)] + [
        (name, b"" if name.endswith("/") else b"x") for name in names
    ]
    return raw_zip(entries, **options)  # ty: ignore[invalid-argument-type]


def _reference_metadata(data: bytes) -> BundleMetadata:
    """compute_bundle_metadata as it was with zipfile.ZipFile."""
    total = count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in sorted(archive.infolist(), key=lambda entry: entry.filename):
            if info.is_dir():
                continue
            total += len(archive.read(info))
            count += 1
    return BundleMetadata(unpacked_size_bytes=total, file_count=count)


@pytest.fixture
def parsed_entries(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Names of every ZipInfo built while the test runs."""
    names: list[str] = []

    class CountingZipInfo(zipfile.ZipInfo):
        __slots__ = ()

        def __init__(
            self,
            filename: str = "NoName",
            date_time: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0),
        ) -> None:
            super().__init__(filename, date_time)
            names.append(filename)

    monkeypatch.setattr(zipfile, "ZipInfo", CountingZipInfo)
    return names


def _assert_metadata_limit(exc: OnyxError) -> None:
    assert exc.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert exc.extra == {
        "limit": "zip_metadata_bytes",
        "limit_value": ZIP_METADATA_MAX_BYTES,
    }


# Each central directory is larger than 4 MiB. The old 4 MiB stored cap
# refused all of them.
_LARGE_DIRECTORIES: dict[str, Callable[[], bytes]] = {
    "many files": lambda: _bundle([f"{index:05d}" for index in range(90_000)]),
    "folders": lambda: _bundle([f"f/{index:05d}/" for index in range(80_000)]),
    "long names": lambda: _bundle([f"{index}/{'n' * 60_000}" for index in range(75)]),
    "long extra fields": lambda: _bundle(
        [f"refs/{index}.md" for index in range(75)], extra_bytes=60_000
    ),
    "long comments": lambda: _bundle(
        [f"refs/{index}.md" for index in range(75)], comment_bytes=60_000
    ),
    "zip64 end record": lambda: _bundle(
        [f"{index:05d}" for index in range(90_000)], zip64=True
    ),
}


@pytest.mark.parametrize("shape", _LARGE_DIRECTORIES)
def test_upload_refuses_large_file_list_before_any_entry_exists(
    shape: str, parsed_entries: list[str]
) -> None:
    zip_bytes = _LARGE_DIRECTORIES[shape]()
    parsed_entries.clear()

    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(zip_bytes, zip_max_bytes=None)
    _assert_metadata_limit(exc_info.value)
    with pytest.raises(OnyxError) as exc_info:
        update_custom_bundle_files(_bundle([]), zip_bytes, filename="files.zip")
    _assert_metadata_limit(exc_info.value)
    assert parsed_entries == []


def test_upload_metadata_limit_fits_500_files_with_long_paths() -> None:
    # Nine 200-byte segments: each name stays within the 255-byte segment limit.
    long_path = "/".join(["p" * 199] * 9)
    zip_bytes = _bundle([f"refs/{index:04d}/{long_path}.md" for index in range(499)])
    assert 500 * 1800 < directory_size(zip_bytes) <= ZIP_METADATA_MAX_BYTES

    assert normalize_custom_bundle(zip_bytes).content is zip_bytes


@pytest.mark.parametrize("shape", _LARGE_DIRECTORIES)
def test_stored_reads_keep_bundles_with_large_file_lists(shape: str) -> None:
    zip_bytes = _LARGE_DIRECTORIES[shape]()
    assert directory_size(zip_bytes) > 4 * _MIB
    files = sum(
        not name.endswith("/")
        for name in zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
    )

    metadata = compute_bundle_metadata(zip_bytes, limits=STORED_BUNDLE_LIMITS)
    assert metadata == _reference_metadata(zip_bytes)
    assert metadata.file_count == files
    assert read_custom_bundle_instructions(zip_bytes) == "Body"
    assert len(inspect_custom_bundle(zip_bytes).files) == files - 1
    stored = normalize_custom_bundle(
        zip_bytes, zip_max_bytes=None, max_file_count=None, stored_read=True
    )
    assert stored.content is zip_bytes
    delivered: dict[str, bytes] = {}
    push._add_bundle_bytes(
        delivered, cast(Skill, SimpleNamespace(name="limits")), stored.content
    )
    assert len(delivered) == files


def test_stored_reads_unwrap_legacy_bundle_with_large_file_list() -> None:
    zip_bytes = _bundle(
        [f"limits/refs/{index}.md" for index in range(75)]
        + ["limits/.DS_Store", "__MACOSX/limits/._SKILL.md", "limits/empty/"],
        skill_md="limits/SKILL.md",
        comment_bytes=60_000,
    )
    assert directory_size(zip_bytes) > 4 * _MIB

    stored = normalize_custom_bundle(
        zip_bytes, zip_max_bytes=None, max_file_count=None, stored_read=True
    )

    assert stored.source_directory == "limits"
    with zipfile.ZipFile(io.BytesIO(stored.content)) as normalized:
        assert normalized.namelist() == ["SKILL.md"] + [
            f"refs/{index}.md" for index in range(75)
        ]
        # Rewritten entries drop per-entry comments and extra fields.
        assert all(info.comment == b"" for info in normalized.infolist())


def _peak(call: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_stored_read_memory_does_not_grow_with_entries() -> None:
    small = _bundle([f"f/{index:05d}/" for index in range(5_000)])
    large = _bundle([f"f/{index:05d}/" for index in range(40_000)])

    def read(data: bytes) -> None:
        compute_bundle_metadata(data, limits=STORED_BUNDLE_LIMITS)
        normalize_custom_bundle(data, zip_max_bytes=None, max_file_count=None)
        inspect_custom_bundle(data)

    assert _peak(lambda: read(large)) < max(512 * 1024, 2 * _peak(lambda: read(small)))
    assert _peak(lambda: read(large)) * 40 < _peak(
        lambda: zipfile.ZipFile(io.BytesIO(large)).infolist()
    )


def test_duplicate_names_keep_zipfile_order_and_last_entry() -> None:
    replaced = _SKILL_MD.replace(b"Body", b"Second")
    zip_bytes = raw_zip(
        [
            ("b.md", b"1"),
            ("SKILL.md", _SKILL_MD),
            ("b.md", b"2"),
            ("SKILL.md", replaced),
        ]
    )

    assert compute_bundle_metadata(zip_bytes) == _reference_metadata(zip_bytes)
    assert read_custom_bundle_instructions(zip_bytes) == "Second"
    assert [file.path for file in inspect_custom_bundle(zip_bytes).files] == [
        "b.md",
        "b.md",
    ]
    with pytest.raises(OnyxError, match="duplicate path 'b.md'"):
        normalize_custom_bundle(
            zip_bytes, zip_max_bytes=None, max_file_count=None, stored_read=True
        )


@pytest.mark.parametrize("path", ["../escape.md", "/absolute.md", "a/../b.md"])
def test_stored_reads_still_refuse_unsafe_paths(path: str) -> None:
    zip_bytes = _bundle([path])

    for read in (
        lambda: inspect_custom_bundle(zip_bytes),
        lambda: normalize_custom_bundle(
            zip_bytes, zip_max_bytes=None, max_file_count=None
        ),
    ):
        with pytest.raises(OnyxError, match="escapes root") as exc_info:
            read()
        assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def _forged(zip64: bool) -> bytes:
    # The end record claims every byte before it is the central directory.
    valid = _bundle([])
    body = valid[: -22 - directory_size(valid)] + b"x" * _MIB
    if zip64:
        return with_zip64_end(body, 1, len(body), 0)
    return body + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(body), 0, 0)


@pytest.mark.parametrize("zip64", [False, True])
def test_forged_directory_sizes_fail_without_partial_state(
    zip64: bool, parsed_entries: list[str]
) -> None:
    zip_bytes = _forged(zip64)
    descriptor_dir = Path("/proc/self/fd")
    descriptors = (
        len(list(descriptor_dir.iterdir())) if descriptor_dir.is_dir() else None
    )
    parsed_entries.clear()

    with pytest.raises(OnyxError) as upload:
        normalize_custom_bundle(zip_bytes)
    _assert_metadata_limit(upload.value)
    assert parsed_entries == []
    with pytest.raises(OnyxError) as stored:
        normalize_custom_bundle(
            zip_bytes, zip_max_bytes=None, max_file_count=None, stored_read=True
        )
    assert stored.value.error_code == OnyxErrorCode.INVALID_INPUT
    with pytest.raises(OnyxError) as inspected:
        inspect_custom_bundle(zip_bytes)
    assert inspected.value.error_code == OnyxErrorCode.INTERNAL_ERROR
    with pytest.raises(zipfile.BadZipFile):
        compute_bundle_metadata(zip_bytes, limits=STORED_BUNDLE_LIMITS)
    if descriptors is not None:
        assert len(list(descriptor_dir.iterdir())) == descriptors


def _zip_with(entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize(
    "path",
    [
        "a/" * 64 + "b",
        "a/" * 32700 + "b",
        "d/" + "x" * 4095,
        "x" * 256,
    ],
    ids=["depth", "deep-64k", "path-bytes", "segment-bytes"],
)
def test_overlong_paths_fail_before_parent_tracking(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    added: list[str] = []
    add = DiskPathSet.add

    def track(self: DiskPathSet, value: str) -> None:
        added.append(value)
        add(self, value)

    monkeypatch.setattr(DiskPathSet, "add", track)
    bundle = _zip_with(
        [("SKILL.md", _SKILL_MD)] + [(f"{i}/{path}", b"x") for i in range(15)]
    )

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(bundle, max_file_count=None)

    assert caught.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "too long or too deep" in caught.value.detail
    assert added == []


def test_paths_at_the_limits_are_accepted() -> None:
    deepest = "/".join(["d"] * 63) + "/" + "f" * 255
    bundle = _zip_with([("SKILL.md", _SKILL_MD), (deepest, b"x")])

    normalized = normalize_custom_bundle(bundle)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as archive:
        assert deepest in archive.namelist()


def test_temporary_storage_errors_are_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full(self: DiskPathSet, value: str) -> None:  # noqa: ARG001
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(DiskPathSet, "add", full)
    bundle = _zip_with([("SKILL.md", _SKILL_MD), ("dir/file.txt", b"x")])

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(bundle)

    assert caught.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE


def test_rewrite_storage_errors_are_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full(self: SpooledZipInfos, info: zipfile.ZipInfo) -> None:  # noqa: ARG001
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(SpooledZipInfos, "append", full)
    # The wrapper directory forces a rewrite, which spools entry metadata.
    bundle = _zip_with([("wrap/SKILL.md", b"---\nname: wrap\ndescription: d\n---\nhi")])

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(
            bundle, zip_max_bytes=None, max_file_count=None, stored_read=True
        )

    assert caught.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.parametrize(
    "reader", ["compute_bundle_metadata", "bundle_skill_md_record"]
)
def test_repair_retries_temporary_storage_errors(
    monkeypatch: pytest.MonkeyPatch, reader: str
) -> None:
    def full(*_args: object, **_kwargs: object) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(
        skill_version, "read_version_bundle", lambda *_a, **_k: _zip_with([])
    )
    monkeypatch.setattr(
        skill_version,
        "compute_bundle_metadata",
        lambda *_a, **_k: BundleMetadata(unpacked_size_bytes=1, file_count=1),
    )
    monkeypatch.setattr(skill_version, reader, full)
    version = SkillVersion(bundle_file_id="bundle")

    with pytest.raises(sqlite3.OperationalError):
        skill_version.repair_version_metadata(
            version, MagicMock(), limits=STORED_BUNDLE_LIMITS
        )

    assert not version.metadata_unrepairable


def test_stored_parent_path_budget_counts_utf8_bytes() -> None:
    # Parents "é" (2 bytes) and "é/ü" (5 bytes).
    assert _parent_path_bytes("é/ü/f") == 7


class _Cp437Info(zipfile.ZipInfo):
    """Writes the name in CP437 without the UTF-8 flag, as older tools do."""

    def _encodeFilenameFlags(self) -> tuple[bytes, int]:
        return self.filename.encode("cp437"), self.flag_bits & ~0x800


def test_rewrite_keeps_file_list_within_the_upload_cap() -> None:
    # Each "é" is 1 byte in CP437 and 2 bytes in the UTF-8 rewrite.
    folders = "/".join(["é" * 120] * 16)
    entries: list[tuple[str | zipfile.ZipInfo, bytes]] = [
        (_Cp437Info("w/SKILL.md"), b"---\nname: w\ndescription: d\n---\nhi")
    ]
    entries += [(_Cp437Info(f"w/{folders}/{index}"), b"x") for index in range(499)]
    bundle = _zip_with(entries)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        source_list_bytes = sum(
            46 + len(i.filename.encode("cp437")) for i in archive.infolist()
        )
    assert source_list_bytes < ZIP_METADATA_MAX_BYTES

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(bundle)

    assert caught.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert "file list" in caught.value.detail


def test_wrapper_strip_drops_unicode_path_extra() -> None:
    # 0x7075 names "../../evil.sh"; its CRC matches the name after the wrapper strip.
    evil = b"../../evil.sh"
    payload = struct.pack("<BL", 1, zlib.crc32(b"foo")) + evil
    member = zipfile.ZipInfo("wrap/foo")
    member.extra = struct.pack("<HH", 0x7075, len(payload)) + payload
    bundle = _zip_with(
        [
            ("wrap/SKILL.md", b"---\nname: wrap\ndescription: d\n---\nhi"),
            (member, b"x"),
        ]
    )

    normalized = normalize_custom_bundle(bundle)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as archive:
        assert sorted(archive.namelist()) == ["SKILL.md", "foo"]
        assert all(info.extra == b"" for info in archive.infolist())
    contents = inspect_custom_bundle(normalized.content)
    assert [file.path for file in contents.files] == ["foo"]


def test_path_caps_apply_to_writes_not_stored_reads() -> None:
    long_segment = f"refs/{'s' * 300}.md"
    bundle = _zip_with([("SKILL.md", _SKILL_MD), (long_segment, b"x")])

    stored = normalize_custom_bundle(
        bundle, zip_max_bytes=None, max_file_count=None, stored_read=True
    )
    assert stored.content is bundle
    assert [file.path for file in inspect_custom_bundle(bundle).files] == [long_segment]
    store = MagicMock()
    store.get_file_size.return_value = len(bundle)
    store.read_file.return_value = io.BytesIO(bundle)
    assert load_stored_custom_skill_bundle("legacy", store).content == bundle

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(bundle)
    assert caught.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "too long or too deep" in caught.value.detail


_LEGACY_LONG_PATH = f"refs/{'s' * 300}.md"


def _legacy_over_cap_bundle() -> bytes:
    return _zip_with(
        [("SKILL.md", _SKILL_MD), (_LEGACY_LONG_PATH, b"x"), ("notes.md", b"n")]
    )


def _paths(bundle: bytes) -> list[str]:
    return [file.path for file in inspect_custom_bundle(bundle).files]


def test_description_edit_keeps_legacy_over_cap_path() -> None:
    edited = rewrite_custom_bundle_skill_md(
        _legacy_over_cap_bundle(),
        canonical_name="limits",
        description="New description",
        instructions_markdown="Body",
    )

    assert _LEGACY_LONG_PATH in _paths(edited)


def test_file_edits_keep_legacy_over_cap_path() -> None:
    added = update_custom_bundle_files(
        _legacy_over_cap_bundle(), b"new", filename="extra.md"
    )
    assert {_LEGACY_LONG_PATH, "extra.md"} <= set(_paths(added))

    removed = update_custom_bundle_files(
        _legacy_over_cap_bundle(), remove_path=_LEGACY_LONG_PATH
    )
    assert _LEGACY_LONG_PATH not in _paths(removed)


def test_file_edit_rejects_a_new_over_cap_path() -> None:
    upload = _zip_with([(f"refs/{'t' * 300}.md", b"x")])

    with pytest.raises(OnyxError) as caught:
        update_custom_bundle_files(
            _legacy_over_cap_bundle(), upload, filename="upload.zip"
        )

    assert caught.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "too long or too deep" in caught.value.detail


def test_stored_read_bounds_parent_paths_before_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    added: list[str] = []
    add = DiskPathSet.add

    def track(self: DiskPathSet, value: str) -> None:
        added.append(value)
        add(self, value)

    monkeypatch.setattr(DiskPathSet, "add", track)
    bundle = _zip_with(
        [("SKILL.md", _SKILL_MD)]
        + [(f"{i}/" + "a/" * 32700 + "b", b"x") for i in range(15)]
    )

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(
            bundle, zip_max_bytes=None, max_file_count=None, stored_read=True
        )

    assert caught.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert caught.value.extra == {
        "limit": "zip_metadata_bytes",
        "limit_value": STORED_PARENT_PATH_MAX_BYTES,
    }
    assert added == []
