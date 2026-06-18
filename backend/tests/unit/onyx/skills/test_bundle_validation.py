"""Unit tests for the custom skill bundle validator.

Covers slug validation, missing SKILL.md, template rejection, size caps, and
the SHA-256 helper. Security-boundary tests (path traversal, symlinks,
_safe_unzip extraction safety) live in test_bundle_safety.py.
"""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import _ZIP_UNIX_CREATE_SYSTEM
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import parse_skill_md_metadata
from onyx.skills.bundle import slug_from_filename
from onyx.skills.bundle import validate_custom_bundle


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


VALID_SKILL_MD = b"# Hello\n\nBody content.\n"


def _valid_bundle() -> bytes:
    return _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("scripts/run.sh", b"#!/bin/sh\necho hi\n"),
            ("docs/notes.md", b"# Notes\n"),
        ]
    )


def test_validator_accepts_a_well_formed_bundle() -> None:
    # No raise = pass; validator returns None.
    assert validate_custom_bundle(_valid_bundle(), slug="hello") is None


def test_validator_rejects_non_zip() -> None:
    with pytest.raises(OnyxError, match="not a valid zip"):
        validate_custom_bundle(b"not a zip", slug="hello")


def test_validator_rejects_missing_skill_md() -> None:
    zip_bytes = _build_zip([("scripts/run.sh", b"#!/bin/sh\n")])
    with pytest.raises(OnyxError, match="SKILL.md missing at bundle root"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_validator_rejects_skill_md_not_at_root() -> None:
    zip_bytes = _build_zip([("subdir/SKILL.md", VALID_SKILL_MD)])
    with pytest.raises(OnyxError, match="SKILL.md missing at bundle root"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_validator_rejects_template_file() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("SKILL.md.template", b"# templated\n"),
        ]
    )
    with pytest.raises(OnyxError, match="cannot ship templates"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_validator_rejects_oversized_single_file() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(OnyxError, match="exceeds"):
        validate_custom_bundle(zip_bytes, slug="hello", per_file_max_bytes=32)


def test_validator_rejects_oversized_total() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", b"x" * 64),
            ("a.bin", b"y" * 64),
            ("b.bin", b"z" * 64),
        ]
    )
    with pytest.raises(OnyxError, match="uncompressed"):
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
def test_validator_rejects_invalid_slug(bad_slug: str) -> None:
    with pytest.raises(OnyxError, match="invalid slug"):
        validate_custom_bundle(_valid_bundle(), slug=bad_slug)


def test_validator_rejects_reserved_slug() -> None:
    """``pptx`` is a codified built-in — bundle uploads using that slug
    are rejected so custom uploads can't shadow a built-in row."""
    with pytest.raises(OnyxError, match="reserved"):
        validate_custom_bundle(_valid_bundle(), slug="pptx")


def test_compute_bundle_sha256_is_deterministic_for_same_bytes() -> None:
    bundle = _valid_bundle()
    assert compute_bundle_sha256(bundle) == compute_bundle_sha256(bundle)


def test_compute_bundle_sha256_differs_when_bytes_differ() -> None:
    a = _valid_bundle()
    b = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("scripts/run.sh", b"#!/bin/sh\necho different\n"),
        ]
    )
    assert compute_bundle_sha256(a) != compute_bundle_sha256(b)


def test_compute_bundle_sha256_differs_for_same_content_different_timestamps() -> None:
    """compute_bundle_sha256 is a raw-bytes hash — same contents repacked with
    different timestamps deliberately hash differently.

    ``deterministic over raw bytes`` — we want to detect "this is the
    exact same upload," not "the contents match."
    """
    entries = [
        ("SKILL.md", VALID_SKILL_MD),
        ("scripts/run.sh", b"#!/bin/sh\n"),
    ]
    a = _build_zip(entries, fixed_date=(2026, 1, 1, 0, 0, 0))
    b = _build_zip(entries, fixed_date=(2026, 6, 15, 12, 30, 0))
    assert a != b
    assert compute_bundle_sha256(a) != compute_bundle_sha256(b)


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


def test_validator_rejects_unsupported_compression() -> None:
    """A ZIP using a stdlib-unknown compression method raises NotImplementedError
    from zf.open() — we must translate that to OnyxError, not a 500."""
    zip_bytes = _zip_with_patched_compression_method(VALID_SKILL_MD, method=99)
    with pytest.raises(OnyxError, match="cannot read"):
        validate_custom_bundle(zip_bytes, slug="hello")


def test_validator_size_violation_returns_413() -> None:
    """Size-cap violations should return HTTP 413, not 400."""
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(OnyxError) as exc_info:
        validate_custom_bundle(zip_bytes, slug="hello", per_file_max_bytes=32)
    assert exc_info.value.status_code == 413


def test_validator_non_size_violation_returns_400() -> None:
    """Non-size violations still return 400."""
    with pytest.raises(OnyxError) as exc_info:
        validate_custom_bundle(b"not a zip", slug="hello")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# slug_from_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("deal-summary.zip", "deal-summary"),
        ("hello.ZIP", "hello"),
        ("plain", "plain"),
    ],
)
def test_slug_from_filename_strips_zip_extension(filename: str, expected: str) -> None:
    assert slug_from_filename(filename) == expected


@pytest.mark.parametrize("bad", [None, "", "Bad-Caps.zip", "with space.zip"])
def test_slug_from_filename_rejects_invalid(bad: str | None) -> None:
    with pytest.raises(OnyxError):
        slug_from_filename(bad)


# ---------------------------------------------------------------------------
# parse_skill_md_metadata
# ---------------------------------------------------------------------------


def _bundle_with_skill_md(body: bytes) -> bytes:
    return _build_zip([("SKILL.md", body)])


def test_parse_skill_md_metadata_happy_path() -> None:
    body = b"---\nname: My Skill\ndescription: Helpful description\n---\n\nbody\n"
    name, description = parse_skill_md_metadata(_bundle_with_skill_md(body))
    assert name == "My Skill"
    assert description == "Helpful description"


def test_parse_skill_md_metadata_strips_whitespace() -> None:
    body = b"---\nname: '  spaced  '\ndescription: ' desc '\n---\n\nbody\n"
    name, description = parse_skill_md_metadata(_bundle_with_skill_md(body))
    assert name == "spaced"
    assert description == "desc"


def test_parse_skill_md_metadata_rejects_missing_frontmatter() -> None:
    with pytest.raises(OnyxError, match="frontmatter"):
        parse_skill_md_metadata(_bundle_with_skill_md(b"no frontmatter here\n"))


def test_parse_skill_md_metadata_rejects_missing_name() -> None:
    body = b"---\ndescription: only a description\n---\n\nbody\n"
    with pytest.raises(OnyxError, match="name"):
        parse_skill_md_metadata(_bundle_with_skill_md(body))


def test_parse_skill_md_metadata_rejects_missing_description() -> None:
    body = b"---\nname: only a name\n---\n\nbody\n"
    with pytest.raises(OnyxError, match="description"):
        parse_skill_md_metadata(_bundle_with_skill_md(body))


def test_parse_skill_md_metadata_rejects_empty_name() -> None:
    body = b"---\nname: ''\ndescription: desc\n---\n\nbody\n"
    with pytest.raises(OnyxError, match="name"):
        parse_skill_md_metadata(_bundle_with_skill_md(body))


def test_parse_skill_md_metadata_rejects_missing_skill_md() -> None:
    zip_bytes = _build_zip([("other.txt", b"hi")])
    with pytest.raises(OnyxError, match="SKILL.md missing"):
        parse_skill_md_metadata(zip_bytes)


def test_parse_skill_md_metadata_rejects_bad_zip() -> None:
    with pytest.raises(OnyxError, match="not a valid zip"):
        parse_skill_md_metadata(b"not a zip")
