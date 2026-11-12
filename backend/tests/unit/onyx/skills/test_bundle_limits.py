"""Unit tests for the skill bundle limits."""

from __future__ import annotations

import io
import os
import random
import zipfile
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.db.models import Skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills import bundle as bundle_module
from onyx.skills import validation
from onyx.skills.bundle import (
    STORED_ZIP_DIRECTORY_MAX_BYTES,
    ZIP_DIRECTORY_MAX_BYTES,
    SkillBundleLimit,
    normalize_custom_bundle,
    read_bundle_file,
    rewrite_custom_bundle_skill_md,
    update_custom_bundle_files,
)
from onyx.skills.content import read_custom_skill_bundle_bytes
from onyx.skills.ingest import ingest_skill_bundle

_MIB = 1024 * 1024
_SKILL_MD = b"---\nname: limits\ndescription: Limit checks\n---\n\n# Instructions\n"


def _build_zip(
    entries: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        for path, data in entries:
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = compression
            zf.writestr(info, data)
    return buf.getvalue()


def _assert_limit_error(
    exc: OnyxError, limit: SkillBundleLimit, limit_value: int
) -> None:
    assert exc.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert exc.status_code == 413
    assert exc.extra == {"limit": limit, "limit_value": limit_value}


def test_read_bundle_file_refuses_26_mib_upload() -> None:
    with pytest.raises(OnyxError) as exc_info:
        read_bundle_file(io.BytesIO(b"\x00" * (26 * _MIB)))

    _assert_limit_error(exc_info.value, "zip_bytes", 25 * _MIB)


def test_read_bundle_file_accepts_upload_at_limit() -> None:
    assert len(read_bundle_file(io.BytesIO(b"\x00" * (25 * _MIB)))) == 25 * _MIB


def test_normalizer_refuses_26_mib_zip_inside_extracted_limits() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", _SKILL_MD),
            ("a.bin", os.urandom(13 * _MIB)),
            ("b.bin", os.urandom(13 * _MIB)),
        ],
        compression=zipfile.ZIP_STORED,
    )
    assert len(zip_bytes) > 26 * _MIB

    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(zip_bytes)

    _assert_limit_error(exc_info.value, "zip_bytes", 25 * _MIB)


def test_normalizer_zip_limit_boundary() -> None:
    zip_bytes = _build_zip([("SKILL.md", _SKILL_MD)])

    normalize_custom_bundle(zip_bytes, zip_max_bytes=len(zip_bytes))
    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(zip_bytes, zip_max_bytes=len(zip_bytes) - 1)

    _assert_limit_error(exc_info.value, "zip_bytes", len(zip_bytes) - 1)


def test_normalizer_refuses_501_files() -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", _SKILL_MD)] + [(f"refs/{index}.md", b"x") for index in range(500)]
    )

    with pytest.raises(OnyxError, match="more than 500 files") as exc_info:
        normalize_custom_bundle(zip_bytes)

    _assert_limit_error(exc_info.value, "file_count", 500)


def test_normalizer_accepts_500_files_without_counting_folders() -> None:
    zip_bytes = _build_zip(
        [("limits/", b""), ("limits/SKILL.md", _SKILL_MD), ("limits/refs/", b"")]
        + [(f"limits/refs/{index}.md", b"x") for index in range(499)]
    )

    normalized = normalize_custom_bundle(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as bundle:
        assert sum(not info.is_dir() for info in bundle.infolist()) == 500


@pytest.mark.parametrize("path", ["__MACOSX/._file", ".DS_Store", "Thumbs.db"])
def test_ignored_files_count_toward_archive_limit(path: str) -> None:
    zip_bytes = _build_zip([("SKILL.md", _SKILL_MD), (path, b"x")])
    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(zip_bytes, max_file_count=1)
    _assert_limit_error(exc_info.value, "file_count", 1)


def test_supporting_file_archive_counts_ignored_entries() -> None:
    upload = _build_zip(
        [("reference.txt", b"x")]
        + [(f"__MACOSX/._{index}", b"x") for index in range(500)]
    )
    with pytest.raises(OnyxError) as exc_info:
        update_custom_bundle_files(
            _build_zip([("SKILL.md", _SKILL_MD)]), upload, filename="files.zip"
        )
    _assert_limit_error(exc_info.value, "file_count", 500)


def test_normalized_zip_must_also_fit_zip_limit() -> None:
    block = random.Random(1).randbytes(64 * 1024)
    upload = _build_zip(
        [("limits/SKILL.md", _SKILL_MD), ("limits/data.bin", block * 2)],
        compression=zipfile.ZIP_LZMA,
    )
    assert len(upload) < 100 * 1024
    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(upload, zip_max_bytes=100 * 1024)
    _assert_limit_error(exc_info.value, "zip_bytes", 100 * 1024)
    assert len(normalize_custom_bundle(upload, zip_max_bytes=None).content) > 100 * 1024


@pytest.mark.parametrize("filename", ["SKILL.md", "reference.txt"])
def test_raw_upload_uses_file_limit(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bundle_module, "DEFAULT_ZIP_MAX_BYTES", 1024)
    monkeypatch.setattr(bundle_module, "DEFAULT_PER_FILE_MAX_BYTES", 2048)
    data = b"a" * 2048
    assert read_bundle_file(io.BytesIO(data), filename=filename) == data
    with pytest.raises(OnyxError) as exc_info:
        read_bundle_file(io.BytesIO(data + b"x"), filename=filename)
    _assert_limit_error(exc_info.value, "file_bytes", 2048)


def test_normalizer_refuses_small_zip_that_unpacks_past_100_mib() -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", _SKILL_MD)]
        + [(f"data/{index}.bin", b"\x00" * (21 * _MIB)) for index in range(5)]
    )
    assert len(zip_bytes) < _MIB

    with pytest.raises(OnyxError, match="uncompressed") as exc_info:
        normalize_custom_bundle(zip_bytes)

    _assert_limit_error(exc_info.value, "total_bytes", 100 * _MIB)


def test_normalizer_refuses_26_mib_file() -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", _SKILL_MD), ("big.bin", b"\x00" * (26 * _MIB))]
    )

    with pytest.raises(OnyxError, match="big.bin") as exc_info:
        normalize_custom_bundle(zip_bytes)

    _assert_limit_error(exc_info.value, "file_bytes", 25 * _MIB)


def test_normalizer_accepts_bundle_at_every_limit() -> None:
    big_files = [(f"data/{index}.bin", b"\x00" * (25 * _MIB)) for index in range(3)]
    big_files.append(("data/3.bin", b"\x00" * (25 * _MIB - len(_SKILL_MD))))
    small_files = [(f"refs/{index}.md", b"") for index in range(495)]
    zip_bytes = _build_zip([("SKILL.md", _SKILL_MD), *big_files, *small_files])
    assert len(zip_bytes) <= 25 * _MIB

    assert normalize_custom_bundle(zip_bytes).content is zip_bytes


def test_skipped_limits_allow_bundles_saved_before_them() -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", _SKILL_MD)] + [(f"refs/{index}.md", b"x") for index in range(600)]
    )

    with pytest.raises(OnyxError):
        normalize_custom_bundle(zip_bytes)
    normalize_custom_bundle(zip_bytes, zip_max_bytes=None, max_file_count=None)


def _stored_skill() -> Skill:
    return cast(Skill, SimpleNamespace(name="limits", bundle_file_id="bundle"))


def test_current_content_read_refuses_bundle_over_total_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limit = 1024
    monkeypatch.setattr(validation, "STORED_ZIP_MAX_BYTES", limit)
    stream = io.BytesIO(b"x" * (limit + 1))
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = stream

    with pytest.raises(OnyxError) as caught:
        read_custom_skill_bundle_bytes(_stored_skill(), file_store)

    _assert_limit_error(caught.value, "zip_bytes", limit)
    assert stream.closed


def test_current_content_read_returns_bundle_within_allowance() -> None:
    stored = _build_zip([("SKILL.md", _SKILL_MD)])
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored)

    assert read_custom_skill_bundle_bytes(_stored_skill(), file_store) == (stored)


def test_full_replacement_does_not_read_existing_bundle() -> None:
    existing = MagicMock(side_effect=AssertionError("existing bundle was read"))
    replacement = _build_zip([("SKILL.md", _SKILL_MD), ("refs/a.md", b"a")])

    updated = update_custom_bundle_files(
        existing, replacement, filename="replacement.zip"
    )

    existing.assert_not_called()
    assert updated == replacement


def test_merge_reads_existing_bundle_once() -> None:
    existing = MagicMock(return_value=_build_zip([("SKILL.md", _SKILL_MD)]))

    updated = update_custom_bundle_files(existing, b"a", filename="a.md")

    existing.assert_called_once_with()
    with zipfile.ZipFile(io.BytesIO(updated)) as archive:
        assert sorted(archive.namelist()) == ["SKILL.md", "a.md"]


def _many_entries(count: int, name_bytes: int) -> bytes:
    return _build_zip(
        [("SKILL.md", _SKILL_MD)]
        + [(f"refs/{index:06d}".ljust(name_bytes, "n"), b"") for index in range(count)],
        compression=zipfile.ZIP_STORED,
    )


def test_upload_with_large_file_list_is_refused_before_entries_are_read() -> None:
    upload = _many_entries(60_000, 1)

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(upload)

    _assert_limit_error(caught.value, "zip_metadata_bytes", ZIP_DIRECTORY_MAX_BYTES)


def test_saved_bundle_over_the_upload_file_list_limit_still_loads() -> None:
    stored = _many_entries(15_000, 60)
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored)

    with pytest.raises(OnyxError):
        normalize_custom_bundle(stored)
    normalized = validation.load_stored_custom_skill_bundle("id", file_store)

    assert normalized.content == stored


def test_saved_bundle_file_list_has_its_own_limit() -> None:
    stored = _many_entries(80_000, 60)
    file_store = MagicMock(spec=FileStore)
    file_store.read_file.return_value = io.BytesIO(stored)

    with pytest.raises(OnyxError) as caught:
        validation.load_stored_custom_skill_bundle("id", file_store)

    _assert_limit_error(
        caught.value, "zip_metadata_bytes", STORED_ZIP_DIRECTORY_MAX_BYTES
    )


def _saved_bundle_over_file_count() -> bytes:
    return _build_zip(
        [("SKILL.md", _SKILL_MD)] + [(f"refs/{index}.md", b"x") for index in range(600)]
    )


def test_metadata_edit_keeps_saved_bundle_over_file_count() -> None:
    edited = rewrite_custom_bundle_skill_md(
        _saved_bundle_over_file_count(),
        canonical_name="limits",
        description="New description",
        instructions_markdown="# New instructions",
    )

    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        assert len(archive.namelist()) == 601
        assert b"New description" in archive.read("SKILL.md")


def test_removal_can_shrink_saved_bundle_over_file_count() -> None:
    updated = update_custom_bundle_files(
        _saved_bundle_over_file_count(), remove_path="refs/0.md"
    )

    with zipfile.ZipFile(io.BytesIO(updated)) as archive:
        assert len(archive.namelist()) == 600
        assert "refs/0.md" not in archive.namelist()


def test_adding_a_file_to_saved_bundle_over_file_count_is_refused() -> None:
    with pytest.raises(OnyxError) as caught:
        update_custom_bundle_files(
            _saved_bundle_over_file_count(), b"new", filename="new.md"
        )

    _assert_limit_error(caught.value, "file_count", 500)


def test_editor_ingest_skips_upload_limits_only_when_asked() -> None:
    saved = _build_zip(
        [
            (
                "SKILL.md",
                b"---\nname: limits\ndescription: Limit checks\n---\n\nBody\n",
            )
        ]
        + [(f"refs/{index}.md", b"x") for index in range(600)]
    )
    file_store = MagicMock(spec=FileStore)
    file_store.save_file.return_value = "bundle-id"

    with pytest.raises(OnyxError):
        ingest_skill_bundle(saved, "limits.zip", file_store, expected_name="limits")
    ingested = ingest_skill_bundle(
        saved,
        "limits.zip",
        file_store,
        expected_name="limits",
        upload_limits=False,
    )

    assert ingested.bundle_file_id == "bundle-id"


def test_edit_that_would_not_load_again_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = _build_zip([("SKILL.md", _SKILL_MD)])
    monkeypatch.setattr(bundle_module, "STORED_ZIP_MAX_BYTES", len(saved) + 16)

    with pytest.raises(OnyxError) as caught:
        rewrite_custom_bundle_skill_md(
            saved,
            canonical_name="limits",
            description="Limit checks",
            instructions_markdown="# Instructions\n\n" + "x" * 4096,
        )

    _assert_limit_error(caught.value, "zip_bytes", len(saved) + 16)
