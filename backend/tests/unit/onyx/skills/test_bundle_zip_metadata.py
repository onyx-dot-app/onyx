"""Skill bundle ZIP metadata: a cap for new uploads, bounded reads for stored ones."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import struct
import tracemalloc
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.db.models import Skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import BundleMetadata
from onyx.skills import push
from onyx.skills.bundle import (
    STORED_BUNDLE_LIMITS,
    ZIP_METADATA_MAX_BYTES,
    _PathSet,
    inspect_custom_bundle,
    normalize_custom_bundle,
    read_custom_bundle_instructions,
    update_custom_bundle_files,
)
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
            _PathSet()
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
    digest = hashlib.sha256()
    total = count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in sorted(archive.infolist(), key=lambda entry: entry.filename):
            if info.is_dir():
                continue
            content = archive.read(info)
            path = info.filename.encode()
            digest.update(len(path).to_bytes(8, "big") + path)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(hashlib.sha256(content).digest())
            total += len(content)
            count += 1
    return BundleMetadata(
        content_digest=digest.hexdigest(), unpacked_size_bytes=total, file_count=count
    )


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
    zip_bytes = _bundle([f"refs/{index:04d}/{'p' * 1800}.md" for index in range(499)])
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
    stored = normalize_custom_bundle(zip_bytes, zip_max_bytes=None, max_file_count=None)
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

    stored = normalize_custom_bundle(zip_bytes, zip_max_bytes=None, max_file_count=None)

    assert stored.source_directory == "limits"
    with zipfile.ZipFile(io.BytesIO(stored.content)) as normalized:
        assert normalized.namelist() == ["SKILL.md"] + [
            f"refs/{index}.md" for index in range(75)
        ]
        assert all(info.comment == b"c" * 60_000 for info in normalized.infolist())


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
        normalize_custom_bundle(zip_bytes, zip_max_bytes=None, max_file_count=None)


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
        normalize_custom_bundle(zip_bytes, zip_max_bytes=None, max_file_count=None)
    assert stored.value.error_code == OnyxErrorCode.INVALID_INPUT
    with pytest.raises(OnyxError) as inspected:
        inspect_custom_bundle(zip_bytes)
    assert inspected.value.error_code == OnyxErrorCode.INTERNAL_ERROR
    with pytest.raises(zipfile.BadZipFile):
        compute_bundle_metadata(zip_bytes, limits=STORED_BUNDLE_LIMITS)
    if descriptors is not None:
        assert len(list(descriptor_dir.iterdir())) == descriptors
