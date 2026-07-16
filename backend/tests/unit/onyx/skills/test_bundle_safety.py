"""Traversal and symlink tests for the custom skill upload boundary."""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import _ZIP_UNIX_CREATE_SYSTEM
from onyx.skills.bundle import normalize_custom_bundle


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


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.txt",
        "foo/../../escape.txt",
        "/etc/passwd",
        "./shouldnotbehere",
    ],
)
def test_validator_rejects_path_traversal(bad_path: str) -> None:
    zip_bytes = _build_zip(
        [
            ("SKILL.md", VALID_SKILL_MD),
            (bad_path, b"oops"),
        ]
    )
    with pytest.raises(OnyxError, match="escapes root"):
        normalize_custom_bundle(zip_bytes)


def test_validator_rejects_symlink() -> None:
    zip_bytes = _build_zip(
        [("SKILL.md", VALID_SKILL_MD)],
        symlinks=[("link", b"/etc/passwd")],
    )
    with pytest.raises(OnyxError, match="symlink"):
        normalize_custom_bundle(zip_bytes)
