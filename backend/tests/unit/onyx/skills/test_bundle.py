"""Unit tests for the custom skill bundle validator (spec §5)."""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest

from onyx.skills.bundle import _safe_unzip
from onyx.skills.bundle import _ZIP_UNIX_CREATE_SYSTEM
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import InvalidBundleError
from onyx.skills.bundle import validate_custom_bundle
from onyx.skills.bundle import VALIDATOR_VERSION

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_zip(
    entries: list[tuple[str, bytes]],
    *,
    symlinks: list[tuple[str, bytes]] | None = None,
    fixed_date: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
) -> bytes:
    """Build a zip in-memory. ``symlinks`` is a list of (path, target) pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries:
            info = zipfile.ZipInfo(filename=path, date_time=fixed_date)
            zf.writestr(info, data)
        for path, target in symlinks or []:
            info = zipfile.ZipInfo(filename=path, date_time=fixed_date)
            info.create_system = _ZIP_UNIX_CREATE_SYSTEM
            info.external_attr = (stat.S_IFLNK | 0o755) << 16
            zf.writestr(info, target)
    return buf.getvalue()


VALID_FRONTMATTER_MD = b"""---
name: hello
description: A friendly hello skill.
---

# Hello

Body content.
"""


def _valid_bundle() -> bytes:
    return _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("scripts/run.sh", b"#!/bin/sh\necho hi\n"),
            ("docs/notes.md", b"# Notes\n"),
        ]
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_bundle_accepted() -> None:
    metadata = validate_custom_bundle(_valid_bundle(), slug="hello")
    assert metadata.frontmatter.name == "hello"
    assert metadata.frontmatter.description == "A friendly hello skill."
    paths = sorted(f.path for f in metadata.files)
    assert paths == ["SKILL.md", "docs/notes.md", "scripts/run.sh"]
    assert metadata.total_uncompressed_bytes == sum(f.size for f in metadata.files)
    assert metadata.validator_version == VALIDATOR_VERSION


def test_valid_bundle_without_frontmatter() -> None:
    zip_bytes = _build_zip([("SKILL.md", b"# Title\n\nNo frontmatter here.\n")])
    metadata = validate_custom_bundle(zip_bytes, slug="hello")
    assert metadata.frontmatter.name is None
    assert metadata.frontmatter.description is None


# ---------------------------------------------------------------------------
# Failure modes — one test per rule from spec §5
# ---------------------------------------------------------------------------


def test_rejects_non_zip() -> None:
    with pytest.raises(InvalidBundleError, match="not a valid zip"):
        validate_custom_bundle(b"not a zip", slug="hello")


def test_rejects_missing_skill_md() -> None:
    zip_bytes = _build_zip([("scripts/run.sh", b"#!/bin/sh\n")])
    with pytest.raises(InvalidBundleError, match="SKILL.md missing at bundle root"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_rejects_skill_md_not_at_root() -> None:
    zip_bytes = _build_zip([("subdir/SKILL.md", VALID_FRONTMATTER_MD)])
    with pytest.raises(InvalidBundleError, match="SKILL.md missing at bundle root"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_rejects_template_file() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("SKILL.md.template", b"# templated\n"),
        ]
    )
    with pytest.raises(InvalidBundleError, match="cannot ship templates"):
        validate_custom_bundle(zip_bytes, slug="hello")


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.txt",
        "foo/../../escape.txt",
        "/etc/passwd",
        "./shouldnotbehere",
    ],
)
def test_rejects_path_traversal(bad_path: str) -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            (bad_path, b"oops"),
        ]
    )
    with pytest.raises(InvalidBundleError, match="escapes root"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_rejects_symlink() -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", VALID_FRONTMATTER_MD)],
        symlinks=[("link", b"/etc/passwd")],
    )
    with pytest.raises(InvalidBundleError, match="symlink"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_rejects_oversized_single_file() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(InvalidBundleError, match="exceeds 0 MiB|exceeds"):
        validate_custom_bundle(zip_bytes, slug="hello", per_file_max_bytes=32)


def test_rejects_oversized_total() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", b"x" * 64),
            ("a.bin", b"y" * 64),
            ("b.bin", b"z" * 64),
        ]
    )
    with pytest.raises(InvalidBundleError, match="uncompressed"):
        validate_custom_bundle(
            zip_bytes,
            slug="hello",
            per_file_max_bytes=1024,
            total_max_bytes=128,
        )


@pytest.mark.parametrize(
    "bad_slug",
    [
        "",
        "Hello",
        "1starts-with-digit",
        "has_underscore",
        "a" * 65,
        "..",
    ],
)
def test_rejects_invalid_slug(bad_slug: str) -> None:
    with pytest.raises(InvalidBundleError, match="invalid slug"):
        validate_custom_bundle(_valid_bundle(), slug=bad_slug)


def test_rejects_reserved_slug() -> None:
    with pytest.raises(InvalidBundleError, match="reserved"):
        validate_custom_bundle(
            _valid_bundle(), slug="pptx", reserved_slugs={"pptx", "image-generation"}
        )


# ---------------------------------------------------------------------------
# compute_bundle_sha256
# ---------------------------------------------------------------------------


def test_sha256_is_deterministic_for_same_bytes() -> None:
    bundle = _valid_bundle()
    assert compute_bundle_sha256(bundle) == compute_bundle_sha256(bundle)


def test_sha256_differs_when_bytes_differ() -> None:
    a = _valid_bundle()
    b = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("scripts/run.sh", b"#!/bin/sh\necho different\n"),
        ]
    )
    assert compute_bundle_sha256(a) != compute_bundle_sha256(b)


def test_sha256_differs_for_same_content_different_timestamps() -> None:
    """compute_bundle_sha256 is a raw-bytes hash — same contents repacked with
    different timestamps deliberately hash differently.

    Spec §5: ``deterministic over raw bytes`` — we want to detect "this is the
    exact same upload," not "the contents match."
    """
    entries = [
        ("SKILL.md", VALID_FRONTMATTER_MD),
        ("scripts/run.sh", b"#!/bin/sh\n"),
    ]
    a = _build_zip(entries, fixed_date=(2026, 1, 1, 0, 0, 0))
    b = _build_zip(entries, fixed_date=(2026, 6, 15, 12, 30, 0))
    assert a != b
    assert compute_bundle_sha256(a) != compute_bundle_sha256(b)


# ---------------------------------------------------------------------------
# _safe_unzip
# ---------------------------------------------------------------------------


def test_safe_unzip_extracts_valid_bundle(tmp_path: Path) -> None:
    _safe_unzip(_valid_bundle(), tmp_path / "out")
    assert (tmp_path / "out" / "SKILL.md").read_bytes() == VALID_FRONTMATTER_MD
    assert (tmp_path / "out" / "scripts" / "run.sh").exists()


def test_safe_unzip_rejects_traversal(tmp_path: Path) -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("../escape.txt", b"x"),
        ]
    )
    with pytest.raises(InvalidBundleError, match="escapes root"):
        _safe_unzip(zip_bytes, tmp_path / "out")


def test_safe_unzip_rejects_symlink(tmp_path: Path) -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", VALID_FRONTMATTER_MD)],
        symlinks=[("link", b"/etc/passwd")],
    )
    with pytest.raises(InvalidBundleError, match="symlink"):
        _safe_unzip(zip_bytes, tmp_path / "out")


def test_safe_unzip_enforces_per_file_cap(tmp_path: Path) -> None:
    """Defense-in-depth: even if upload validation is bypassed or the stored
    blob is tampered, extraction must not write unbounded data to disk."""
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(InvalidBundleError, match="exceeds"):
        _safe_unzip(zip_bytes, tmp_path / "out", per_file_max_bytes=32)


def test_safe_unzip_enforces_total_cap(tmp_path: Path) -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", b"x" * 64),
            ("a.bin", b"y" * 64),
            ("b.bin", b"z" * 64),
        ]
    )
    with pytest.raises(InvalidBundleError, match="uncompressed"):
        _safe_unzip(
            zip_bytes,
            tmp_path / "out",
            per_file_max_bytes=1024,
            total_max_bytes=128,
        )


# ---------------------------------------------------------------------------
# Error translation — corrupt / exotic compression
# ---------------------------------------------------------------------------


def _zip_with_patched_compression_method(payload: bytes, method: int) -> bytes:
    """Build a valid ZIP_STORED zip, then patch the compression-method field
    in both the local header and the central directory to ``method``.

    `zipfile.ZipFile(...).writestr()` refuses to write an unknown method, but
    `zipfile.ZipFile(...).open()` happily reads what it can and raises
    `NotImplementedError` when it can't — which is exactly the failure mode we
    want to exercise.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("SKILL.md", payload)
    raw = bytearray(buf.getvalue())
    # Patch every occurrence of the compression-method field. In each header
    # the method is a little-endian uint16 at a fixed offset from the magic.
    for magic, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        pos = raw.find(magic)
        if pos != -1:
            raw[pos + offset : pos + offset + 2] = method.to_bytes(2, "little")
    return bytes(raw)


def test_rejects_unsupported_compression() -> None:
    """A ZIP using a stdlib-unknown compression method raises NotImplementedError
    from zf.open() — we must translate that to InvalidBundleError, not a 500."""
    zip_bytes = _zip_with_patched_compression_method(VALID_FRONTMATTER_MD, method=99)
    with pytest.raises(InvalidBundleError, match="cannot read"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_safe_unzip_rejects_unsupported_compression(tmp_path: Path) -> None:
    zip_bytes = _zip_with_patched_compression_method(VALID_FRONTMATTER_MD, method=99)
    with pytest.raises(InvalidBundleError, match="cannot extract"):
        _safe_unzip(zip_bytes, tmp_path / "out")


# ---------------------------------------------------------------------------
# Error code mapping
# ---------------------------------------------------------------------------


def test_size_violation_returns_413() -> None:
    """Spec §5 size-cap violations should return HTTP 413, not 400."""
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_FRONTMATTER_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(InvalidBundleError) as exc_info:
        validate_custom_bundle(zip_bytes, slug="hello", per_file_max_bytes=32)
    assert exc_info.value.status_code == 413


def test_validation_violation_returns_400() -> None:
    """Non-size violations still return 400."""
    with pytest.raises(InvalidBundleError) as exc_info:
        validate_custom_bundle(b"not a zip", slug="hello")
    assert exc_info.value.status_code == 400
