"""
Unit tests for filename sanitization in Content-Disposition headers.

These tests verify that the sanitize_filename_for_header function correctly
prevents HTTP header injection attacks by removing control characters and
escaping quotes.
"""

import pytest

from onyx.server.query_and_chat.chat_backend import sanitize_filename_for_header


class TestSanitizeFilenameForHeader:
    """Tests for the sanitize_filename_for_header function."""

    def test_normal_filename_unchanged(self) -> None:
        """Test that normal filenames pass through unchanged."""
        assert sanitize_filename_for_header("document.pdf") == "document.pdf"
        assert sanitize_filename_for_header("my_file.txt") == "my_file.txt"
        assert sanitize_filename_for_header("report-2024.docx") == "report-2024.docx"

    def test_filename_with_spaces(self) -> None:
        """Test that filenames with spaces are preserved."""
        assert sanitize_filename_for_header("my document.pdf") == "my document.pdf"
        assert (
            sanitize_filename_for_header("file with many spaces.txt")
            == "file with many spaces.txt"
        )

    def test_double_quotes_escaped(self) -> None:
        """Test that double quotes are escaped to prevent header format breakage."""
        assert sanitize_filename_for_header('file"name.txt') == 'file\\"name.txt'
        assert sanitize_filename_for_header('"quoted".pdf') == '\\"quoted\\".pdf'
        assert (
            sanitize_filename_for_header('a"b"c"d.txt') == 'a\\"b\\"c\\"d.txt'
        )

    def test_newline_removed(self) -> None:
        """Test that newline characters are removed to prevent header injection."""
        assert sanitize_filename_for_header("file\nname.txt") == "filename.txt"
        assert sanitize_filename_for_header("file\r\nname.txt") == "filename.txt"
        assert sanitize_filename_for_header("\nstart.txt") == "start.txt"
        assert sanitize_filename_for_header("end.txt\n") == "end.txt"

    def test_carriage_return_removed(self) -> None:
        """Test that carriage return characters are removed."""
        assert sanitize_filename_for_header("file\rname.txt") == "filename.txt"
        assert sanitize_filename_for_header("\rstart.txt") == "start.txt"

    def test_null_byte_removed(self) -> None:
        """Test that null bytes are removed."""
        assert sanitize_filename_for_header("file\x00name.txt") == "filename.txt"
        assert sanitize_filename_for_header("\x00start.txt") == "start.txt"

    def test_tab_removed(self) -> None:
        """Test that tab characters are removed."""
        assert sanitize_filename_for_header("file\tname.txt") == "filename.txt"

    def test_all_control_characters_removed(self) -> None:
        """Test that all ASCII control characters (0x00-0x1f, 0x7f) are removed."""
        # Test a few representative control characters
        assert sanitize_filename_for_header("a\x01b.txt") == "ab.txt"  # SOH
        assert sanitize_filename_for_header("a\x1fb.txt") == "ab.txt"  # Unit separator
        assert sanitize_filename_for_header("a\x7fb.txt") == "ab.txt"  # DEL

    def test_header_injection_attack_prevented(self) -> None:
        """Test that HTTP header injection attacks are prevented."""
        # Attempt to inject a new header via CRLF
        malicious = "file.txt\r\nX-Injected: malicious"
        result = sanitize_filename_for_header(malicious)
        assert "\r" not in result
        assert "\n" not in result
        assert result == "file.txtX-Injected: malicious"

    def test_combined_attack_prevented(self) -> None:
        """Test that combined quote and newline attacks are prevented."""
        # Attempt to break out of quotes and inject header
        malicious = 'file.txt"\r\nX-Injected: value'
        result = sanitize_filename_for_header(malicious)
        assert "\r" not in result
        assert "\n" not in result
        assert '"' not in result or '\\"' in result
        assert result == 'file.txt\\"X-Injected: value'

    def test_unicode_preserved(self) -> None:
        """Test that Unicode characters are preserved."""
        assert sanitize_filename_for_header("документ.pdf") == "документ.pdf"
        assert sanitize_filename_for_header("文件.txt") == "文件.txt"
        assert sanitize_filename_for_header("café.doc") == "café.doc"

    def test_empty_string(self) -> None:
        """Test that empty string returns empty string."""
        assert sanitize_filename_for_header("") == ""

    def test_only_control_characters(self) -> None:
        """Test that a string of only control characters returns empty string."""
        assert sanitize_filename_for_header("\r\n\t\x00") == ""
