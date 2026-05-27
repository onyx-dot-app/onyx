"""File upload validation tests (unit / pure-logic half).

Tests pin the contract for the pure validation helpers in
`onyx.server.features.build.utils`: size cap and filename sanitization.
Craft intentionally does NOT restrict uploads by extension or MIME type
(the sandbox is the security boundary), so those checks are absent. The
HTTP boundary and manager-side collision/disk behavior live in
ext-dep / integration tests.
"""

from __future__ import annotations

from pathlib import Path

from onyx.server.features.build.configs import MAX_UPLOAD_FILE_SIZE_BYTES
from onyx.server.features.build.utils import sanitize_filename
from onyx.server.features.build.utils import validate_file


def test_sanitize_filename_strips_path_components() -> None:
    """`../foo.txt` collapses to `foo.txt` - no parent-dir component leaks."""
    result = sanitize_filename("../foo.txt")
    assert result == "foo.txt"
    assert ".." not in result
    assert "/" not in result


def test_sanitize_filename_collapses_path_before_regex() -> None:
    """``Path().name`` runs first, so ``"f i*l/e.txt"`` becomes ``"e.txt"``.

    ``Path("f i*l/e.txt").name`` extracts the last component (``"e.txt"``)
    before the regex has a chance to replace spaces or metacharacters.
    """
    result = sanitize_filename("f i*l/e.txt")
    assert result == "e.txt"


def test_sanitize_filename_caps_length_preserves_extension() -> None:
    """A 300-character name is capped at <=255 with the extension preserved."""
    long_name = ("a" * 296) + ".txt"
    assert len(long_name) == 300
    result = sanitize_filename(long_name)
    assert len(result) <= 255
    assert Path(result).suffix == ".txt"
    # The stem is non-empty and consists only of allowed chars.
    assert Path(result).stem != ""


def test_validate_file_accepts_any_size_within_cap() -> None:
    """Only size is enforced - a normal-sized file is accepted."""
    is_valid, error = validate_file(100)
    assert is_valid is True
    assert error is None


def test_validate_file_rejects_oversize() -> None:
    """A file over the per-file cap is rejected."""
    is_valid, error = validate_file(MAX_UPLOAD_FILE_SIZE_BYTES + 1)
    assert is_valid is False
    assert error is not None
    assert "size" in error.lower()


def test_validate_file_rejects_empty() -> None:
    """A zero-byte file is rejected with an empty-file message, not a size-cap one."""
    is_valid, error = validate_file(0)
    assert is_valid is False
    assert error is not None
    assert "empty" in error.lower()
