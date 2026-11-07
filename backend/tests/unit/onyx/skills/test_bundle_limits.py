"""Unit tests for the separate per-version skill bundle limits."""

from __future__ import annotations

import io
import os
import zipfile

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import (
    SkillBundleLimit,
    normalize_custom_bundle,
    read_bundle_file,
)

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
        + [("__MACOSX/limits/._SKILL.md", b"x"), ("limits/.DS_Store", b"x")]
    )

    normalized = normalize_custom_bundle(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as bundle:
        assert sum(not info.is_dir() for info in bundle.infolist()) == 500


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
