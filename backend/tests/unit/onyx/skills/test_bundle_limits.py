"""Unit tests for the separate per-version skill bundle limits."""

from __future__ import annotations

import io
import os
import random
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills import bundle as bundle_module
from onyx.skills.bundle import (
    SkillBundleLimit,
    normalize_custom_bundle,
    read_bundle_file,
    update_custom_bundle_files,
)

_MIB = 1024 * 1024
_SKILL_MD = b"---\nname: limits\ndescription: Limit checks\n---\n\n# Instructions\n"


@pytest.mark.parametrize("upload_limit,expected", [(8192, 4096), (1024, 1024)])
def test_upload_limit_cannot_exceed_stored_allowance(
    upload_limit: int,
    expected: int,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from onyx.skills.bundle import DEFAULT_ZIP_MAX_BYTES, DEFAULT_STORED_ZIP_MAX_BYTES, STORED_BUNDLE_LIMITS; print(DEFAULT_ZIP_MAX_BYTES, DEFAULT_STORED_ZIP_MAX_BYTES, STORED_BUNDLE_LIMITS.max_stored_bytes)",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[4]),
            "SKILL_BUNDLE_ZIP_MAX_BYTES": str(upload_limit),
            "SKILL_BUNDLE_STORED_ZIP_MAX_BYTES": "4096",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip() == f"{expected} 4096 4096"


def _bundle_settings(env: dict[str, str]) -> list[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import io\n"
            "from onyx.error_handling.exceptions import OnyxError\n"
            "from onyx.skills import bundle\n"
            "print(bundle.DEFAULT_STORED_ZIP_MAX_BYTES)\n"
            "print(bundle.SKILL_BUNDLE_SETTINGS_ERROR)\n"
            "try:\n"
            "    bundle.read_bundle_file(io.BytesIO(b'x'))\n"
            "    print('read')\n"
            "except OnyxError as exc:\n"
            "    print(exc.status_code, exc.detail)\n",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[4]),
            **env,
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip().splitlines()


@pytest.mark.parametrize("raw", ["abc", "0", "-1"])
def test_invalid_setting_disables_bundles_without_failing_import(raw: str) -> None:
    _, error, read = _bundle_settings({"SKILL_BUNDLE_TOTAL_MAX_BYTES": raw})

    expected = (
        "Custom skill bundles are disabled because "
        "SKILL_BUNDLE_TOTAL_MAX_BYTES must be a positive integer."
    )
    assert error == expected
    assert read == f"503 {expected}"


def test_invalid_setting_blocks_editor_rewrite_with_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = "SKILL_BUNDLE_PER_FILE_MAX_BYTES must be a positive integer."
    monkeypatch.setattr(bundle_module, "SKILL_BUNDLE_SETTINGS_ERROR", error)
    monkeypatch.setattr(bundle_module, "DEFAULT_PER_FILE_MAX_BYTES", 0)

    with pytest.raises(OnyxError) as exc_info:
        bundle_module.rewrite_custom_bundle_skill_md(
            bundle_module.build_single_file_bundle("SKILL.md", _SKILL_MD),
            canonical_name="limits",
            description="Limit checks",
            instructions_markdown="# Instructions",
        )

    assert exc_info.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    assert exc_info.value.detail == error


def test_invalid_setting_blocks_stored_size_check_with_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = "SKILL_BUNDLE_STORED_ZIP_MAX_BYTES must be a positive integer."
    monkeypatch.setattr(bundle_module, "SKILL_BUNDLE_SETTINGS_ERROR", error)

    with pytest.raises(OnyxError) as exc_info:
        bundle_module.check_stored_zip_size(1, 0)

    assert exc_info.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE


def test_stored_allowance_follows_a_raised_total_limit() -> None:
    total = 300 * _MIB
    stored, error, read = _bundle_settings({"SKILL_BUNDLE_TOTAL_MAX_BYTES": str(total)})

    assert int(stored) == bundle_module.stored_zip_allowance(total, 500) > total
    assert (error, read) == ("None", "read")
    explicit, _, _ = _bundle_settings(
        {
            "SKILL_BUNDLE_TOTAL_MAX_BYTES": str(total),
            "SKILL_BUNDLE_STORED_ZIP_MAX_BYTES": "4096",
        }
    )
    assert explicit == "4096"


def test_incompressible_bundle_at_every_limit_reads_back() -> None:
    """A bundle stored before the ZIP limit can fill the total and file count."""
    count = bundle_module.DEFAULT_MAX_FILE_COUNT
    total = bundle_module.DEFAULT_TOTAL_MAX_BYTES
    noise = random.Random(17).randbytes(total // count + 1)
    remaining = total - len(_SKILL_MD)
    entries = [("SKILL.md", _SKILL_MD)]
    for index in range(1, count):
        size = remaining // (count - index)
        remaining -= size
        entries.append((f"refs/{index:03d}-{'n' * 180}.bin", noise[:size]))
    stored = _build_zip(entries)
    assert len(stored) > max(100 * _MIB, total)

    read = read_bundle_file(
        io.BytesIO(stored), max_bytes=bundle_module.DEFAULT_STORED_ZIP_MAX_BYTES
    )
    normalized = normalize_custom_bundle(read, zip_max_bytes=None, max_file_count=None)

    assert normalized.content == stored


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


@pytest.mark.parametrize(
    ("limit", "label"),
    [(1024, "1,024 bytes"), (_MIB + 1, "1,048,577 bytes"), (_MIB, "1 MiB")],
)
def test_zip_refusal_reports_exact_configured_limit(limit: int, label: str) -> None:
    with pytest.raises(OnyxError) as caught:
        read_bundle_file(io.BytesIO(b"x" * (limit + 1)), max_bytes=limit)
    _assert_limit_error(caught.value, "zip_bytes", limit)
    assert caught.value.detail == f"Skill bundle zip exceeds the {label} limit."


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

    with pytest.raises(OnyxError) as caught:
        normalize_custom_bundle(zip_bytes, max_file_count=500)
    _assert_limit_error(caught.value, "file_count", 500)
    normalize_custom_bundle(zip_bytes, zip_max_bytes=None, max_file_count=None)
