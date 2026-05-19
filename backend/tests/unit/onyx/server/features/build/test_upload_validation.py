"""File upload validation tests (unit / pure-logic half).

Tests pin the contract for the pure validation helpers in
`onyx.server.features.build.utils`: extension allowlist, MIME allowlist,
size cap, and filename sanitization. The HTTP boundary and manager-side
collision/disk behavior live in ext-dep / integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from onyx.server.features.build.configs import MAX_UPLOAD_FILE_SIZE_BYTES
from onyx.server.features.build.utils import sanitize_filename
from onyx.server.features.build.utils import validate_file
from onyx.server.features.build.utils import validate_file_extension
from onyx.server.features.build.utils import validate_mime_type


@pytest.mark.parametrize("filename", ["data.csv", "notes.txt", "report.pdf"])
def test_allowed_extension_accepted(filename: str) -> None:
    """Common allowed extensions (.csv, .txt, .pdf) pass extension validation."""
    is_valid, error = validate_file_extension(filename)
    assert is_valid is True
    assert error is None


@pytest.mark.parametrize("filename", ["malware.exe", "payload.dll"])
def test_blocked_extension_rejected(filename: str) -> None:
    """Executable extensions are rejected with an error message."""
    is_valid, error = validate_file_extension(filename)
    assert is_valid is False
    assert error is not None
    assert "not allowed" in error


def test_mime_type_must_be_allowed() -> None:
    """A MIME type outside the allowlist is rejected; allowed types pass."""
    # Allowed type passes.
    assert validate_mime_type("text/csv") is True
    # Disallowed type is rejected.
    assert validate_mime_type("application/x-msdownload") is False
    # Empty / None Content-Type is permitted (extension-only validation).
    assert validate_mime_type(None) is True
    assert validate_mime_type("") is True


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


@pytest.mark.parametrize(
    "filename, content_type, size, expected_valid, error_fragment",
    [
        # Extension check trips first.
        ("evil.exe", "application/octet-stream", 100, False, "not allowed"),
        # MIME check trips when extension is fine but content type is wrong.
        ("data.csv", "application/x-msdownload", 100, False, "MIME"),
        # Size check trips when extension + MIME are fine but size is over cap.
        (
            "data.csv",
            "text/csv",
            MAX_UPLOAD_FILE_SIZE_BYTES + 1,
            False,
            "size",
        ),
        # Happy path: all three pass.
        ("data.csv", "text/csv", 100, True, None),
    ],
)
def test_validate_file_combines_extension_mime_size(
    filename: str,
    content_type: str,
    size: int,
    expected_valid: bool,
    error_fragment: str | None,
) -> None:
    """`validate_file` applies all three checks; each can independently reject."""
    is_valid, error = validate_file(filename, content_type, size)
    assert is_valid is expected_valid
    if expected_valid:
        assert error is None
    else:
        assert error is not None
        assert error_fragment is not None
        assert error_fragment.lower() in error.lower()
