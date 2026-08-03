"""Unit tests for custom skill bundle validation and normalization."""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import (
    _ZIP_UNIX_CREATE_SYSTEM,
    compute_bundle_sha256,
    normalize_custom_bundle,
    read_custom_bundle_instructions,
    rewrite_custom_bundle_skill_md,
    strip_skill_md_frontmatter,
)
from onyx.skills.metadata import parse_skill_document


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


def test_validate_and_normalize_rejects_non_zip() -> None:
    with pytest.raises(OnyxError, match="not a valid zip"):
        normalize_custom_bundle(b"not a zip")


def test_validate_and_normalize_rejects_missing_skill_md() -> None:
    zip_bytes = _build_zip([("scripts/run.sh", b"#!/bin/sh\n")])
    with pytest.raises(OnyxError, match="SKILL.md missing at bundle root"):
        normalize_custom_bundle(zip_bytes)


def test_normalizer_flattens_single_wrapper_directory() -> None:
    zip_bytes = _build_zip(
        [
            ("hello/SKILL.md", VALID_SKILL_MD),
            ("hello/scripts/run.sh", b"#!/bin/sh\n"),
        ]
    )

    normalized = normalize_custom_bundle(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as zf:
        assert set(zf.namelist()) == {"SKILL.md", "scripts/run.sh"}
        assert zf.read("SKILL.md") == VALID_SKILL_MD


def test_normalizer_leaves_canonical_bundle_bytes_unchanged() -> None:
    zip_bytes = _valid_bundle()
    assert normalize_custom_bundle(zip_bytes).content is zip_bytes


def test_normalizer_rejects_skill_md_nested_more_than_one_directory() -> None:
    zip_bytes = _build_zip([("outer/inner/SKILL.md", VALID_SKILL_MD)])
    with pytest.raises(OnyxError, match="SKILL.md missing at bundle root"):
        normalize_custom_bundle(zip_bytes)


def test_normalizer_rejects_files_outside_wrapper_directory() -> None:
    zip_bytes = _build_zip(
        [
            ("hello/SKILL.md", VALID_SKILL_MD),
            ("unrelated.txt", b"not part of the skill"),
        ]
    )
    with pytest.raises(OnyxError, match="outside the directory"):
        normalize_custom_bundle(zip_bytes)


def test_normalizer_rejects_multiple_wrapped_skills() -> None:
    zip_bytes = _build_zip(
        [
            ("first/SKILL.md", VALID_SKILL_MD),
            ("second/SKILL.md", VALID_SKILL_MD),
        ]
    )
    with pytest.raises(OnyxError, match="SKILL.md missing at bundle root"):
        normalize_custom_bundle(zip_bytes)


def test_normalizer_rejects_duplicate_output_paths() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        zip_bytes = _build_zip(
            [
                ("hello/SKILL.md", VALID_SKILL_MD),
                ("hello/scripts/run.sh", b"first"),
                ("hello/scripts/run.sh", b"second"),
            ]
        )
    with pytest.raises(OnyxError, match="duplicate path 'scripts/run.sh'"):
        normalize_custom_bundle(zip_bytes)


@pytest.mark.parametrize(
    "supporting_entries",
    [
        [("hello/scripts", b"file"), ("hello/scripts/run.sh", b"script")],
        [("hello/scripts/run.sh", b"script"), ("hello/scripts", b"file")],
    ],
)
def test_normalizer_rejects_file_descendant_path_collisions(
    supporting_entries: list[tuple[str, bytes]],
) -> None:
    zip_bytes = _build_zip([("hello/SKILL.md", VALID_SKILL_MD), *supporting_entries])

    with pytest.raises(OnyxError, match="conflicting path"):
        normalize_custom_bundle(zip_bytes)


@pytest.mark.parametrize(
    "supporting_entries",
    [
        [("hello/scripts/", b""), ("hello/scripts", b"file")],
        [("hello/scripts", b"file"), ("hello/scripts/", b"")],
        [("hello/scripts/nested/", b""), ("hello/scripts", b"file")],
        [("hello/scripts", b"file"), ("hello/scripts/nested/", b"")],
    ],
)
def test_normalizer_rejects_explicit_directory_file_collisions(
    supporting_entries: list[tuple[str, bytes]],
) -> None:
    zip_bytes = _build_zip([("hello/SKILL.md", VALID_SKILL_MD), *supporting_entries])

    with pytest.raises(OnyxError, match="conflicting path"):
        normalize_custom_bundle(zip_bytes)


def test_normalizer_accepts_file_beneath_explicit_directory() -> None:
    zip_bytes = _build_zip(
        [
            ("hello/SKILL.md", VALID_SKILL_MD),
            ("hello/scripts/", b""),
            ("hello/scripts/run.sh", b"script"),
        ]
    )

    normalized = normalize_custom_bundle(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as zf:
        assert set(zf.namelist()) == {"SKILL.md", "scripts/run.sh"}


def test_normalizer_ignores_operating_system_metadata() -> None:
    zip_bytes = _build_zip(
        [
            ("hello/SKILL.md", VALID_SKILL_MD),
            ("hello/.DS_Store", b"metadata"),
            ("__MACOSX/hello/._SKILL.md", b"resource fork"),
        ]
    )

    normalized = normalize_custom_bundle(zip_bytes)

    with zipfile.ZipFile(io.BytesIO(normalized.content)) as zf:
        assert zf.namelist() == ["SKILL.md"]


def test_validator_rejects_template_file() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("SKILL.md.template", b"# templated\n"),
        ]
    )
    with pytest.raises(OnyxError, match="cannot ship templates"):
        normalize_custom_bundle(zip_bytes)


def test_validator_rejects_oversized_single_file() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(OnyxError, match="exceeds"):
        normalize_custom_bundle(zip_bytes, per_file_max_bytes=32)


def test_normalizer_preserves_size_error_when_entry_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip_bytes = _build_zip([("hello/SKILL.md", b"x" * 64)])
    original_close = zipfile._ZipWriteFile.close  # ty: ignore[unresolved-attribute]

    def failing_close(
        writer: zipfile._ZipWriteFile,  # ty: ignore[unresolved-attribute]
    ) -> None:
        original_close(writer)
        raise OSError("close failed")

    monkeypatch.setattr(
        zipfile._ZipWriteFile,  # ty: ignore[unresolved-attribute]
        "close",
        failing_close,
    )

    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(zip_bytes, per_file_max_bytes=32)

    assert exc_info.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE


def test_validator_rejects_oversized_total() -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", b"x" * 64),
            ("a.bin", b"y" * 64),
            ("b.bin", b"z" * 64),
        ]
    )
    with pytest.raises(OnyxError, match="uncompressed"):
        normalize_custom_bundle(
            zip_bytes,
            per_file_max_bytes=1024,
            total_max_bytes=128,
        )


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


def test_strip_skill_md_frontmatter_returns_instruction_body() -> None:
    content = (
        "---\nname: Demo\ndescription: Demo skill\n---\n\n# Instructions\n\nDo it."
    )
    assert strip_skill_md_frontmatter(content) == "# Instructions\n\nDo it."


def test_read_custom_bundle_instructions_returns_instruction_body() -> None:
    zip_bytes = _build_zip(
        [
            (
                "SKILL.md",
                b"---\nname: Demo\ndescription: Demo skill\n---\n\n# Instructions\n\nDo it.",
            ),
            ("scripts/run.py", b"print('hi')\n"),
            ("docs/notes.md", b"# Notes\n"),
        ]
    )
    assert read_custom_bundle_instructions(zip_bytes) == "# Instructions\n\nDo it."


def test_read_custom_bundle_instructions_does_not_require_frontmatter() -> None:
    zip_bytes = _build_zip([("SKILL.md", b"# Instructions\n\nDo it.")])
    assert read_custom_bundle_instructions(zip_bytes) == "# Instructions\n\nDo it."


def test_rewrite_custom_bundle_skill_md_preserves_supporting_files() -> None:
    original = _build_zip(
        [
            (
                "SKILL.md",
                b"---\nname: Old\ndescription: Old desc\n---\n\nOld instructions.",
            ),
            ("scripts/run.py", b"print('hi')\n"),
            ("docs/notes.md", b"# Notes\n"),
        ]
    )

    rewritten = rewrite_custom_bundle_skill_md(
        original,
        canonical_name="hello",
        description="New desc",
        instructions_markdown="# New instructions\n\nDo it.",
    )

    assert read_custom_bundle_instructions(rewritten) == "# New instructions\n\nDo it."
    with zipfile.ZipFile(io.BytesIO(rewritten)) as zf:
        metadata = parse_skill_document(zf.read("SKILL.md")).metadata
        assert (metadata.name, metadata.description) == ("hello", "New desc")
        assert zf.read("scripts/run.py") == b"print('hi')\n"
        assert zf.read("docs/notes.md") == b"# Notes\n"


def test_rewrite_custom_bundle_skill_md_preserves_other_frontmatter() -> None:
    original = _build_zip(
        [
            (
                "SKILL.md",
                b"---\n"
                b"name: Old\n"
                b"description: Old desc\n"
                b"license: Apache-2.0\n"
                b"compatibility: Requires git\n"
                b"metadata:\n"
                b"  author: onyx\n"
                b"allowed-tools: Read\n"
                b"x-custom: preserved\n"
                b"---\n\nOld instructions.\n",
            )
        ]
    )

    rewritten = rewrite_custom_bundle_skill_md(
        original,
        canonical_name="hello",
        description="New desc",
        instructions_markdown="New instructions.",
    )

    with zipfile.ZipFile(io.BytesIO(rewritten)) as zf:
        skill_md = zf.read("SKILL.md").decode()
    assert "license: Apache-2.0" in skill_md
    assert "compatibility: Requires git" in skill_md
    assert "author: onyx" in skill_md
    assert "allowed-tools: Read" in skill_md
    assert "x-custom: preserved" in skill_md


def test_rewrite_custom_bundle_skill_md_rejects_oversized_skill_md_before_zip_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.skills.bundle.DEFAULT_PER_FILE_MAX_BYTES", 128)

    with pytest.raises(OnyxError) as exc_info:
        rewrite_custom_bundle_skill_md(
            b"not a zip",
            canonical_name="hello",
            description="New desc",
            instructions_markdown="x" * 256,
        )

    assert exc_info.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE


def test_rewrite_custom_bundle_skill_md_rejects_missing_skill_md() -> None:
    original = _build_zip([("scripts/run.py", b"print('hi')\n")])

    with pytest.raises(OnyxError) as exc_info:
        rewrite_custom_bundle_skill_md(
            original,
            canonical_name="hello",
            description="New desc",
            instructions_markdown="# New instructions\n\nDo it.",
        )

    assert exc_info.value.error_code == OnyxErrorCode.INTERNAL_ERROR
    assert exc_info.value.detail == "Stored skill bundle is missing SKILL.md."


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
        normalize_custom_bundle(zip_bytes)


def test_validator_size_violation_returns_413() -> None:
    """Size-cap violations should return HTTP 413, not 400."""
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            ("big.bin", b"\x00" * 64),
        ]
    )
    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(zip_bytes, per_file_max_bytes=32)
    assert exc_info.value.status_code == 413


def test_validator_non_size_violation_returns_400() -> None:
    """Non-size violations still return 400."""
    with pytest.raises(OnyxError) as exc_info:
        normalize_custom_bundle(b"not a zip")
    assert exc_info.value.status_code == 400
