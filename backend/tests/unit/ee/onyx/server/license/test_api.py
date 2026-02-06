"""Tests for license API utilities."""

from ee.onyx.server.license.api import _strip_pem_delimiters


class TestStripPemDelimiters:
    """Tests for the PEM delimiter stripping function."""

    def test_strips_pem_delimiters(self) -> None:
        """Content wrapped in PEM delimiters is extracted correctly."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----"""

        result = _strip_pem_delimiters(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_handles_multiline_content(self) -> None:
        """Multiline base64 content between delimiters is preserved."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjog
IjEuMCIsICJ0ZW5hbnRfaWQiOiAidGVz
dCJ9LCAic2lnbmF0dXJlIjogImFiYyJ9
-----END ONYX LICENSE-----"""

        result = _strip_pem_delimiters(content)

        expected = """eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjog
IjEuMCIsICJ0ZW5hbnRfaWQiOiAidGVz
dCJ9LCAic2lnbmF0dXJlIjogImFiYyJ9"""
        assert result == expected

    def test_returns_unchanged_without_delimiters(self) -> None:
        """Content without PEM delimiters is returned unchanged."""
        content = "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

        result = _strip_pem_delimiters(content)

        assert result == content

    def test_handles_whitespace(self) -> None:
        """Leading/trailing whitespace is handled correctly."""
        content = """
  -----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----
  """

        result = _strip_pem_delimiters(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_partial_delimiters_unchanged(self) -> None:
        """Content with only begin or only end delimiter is returned unchanged."""
        begin_only = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="""

        end_only = """eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----"""

        assert _strip_pem_delimiters(begin_only) == begin_only.strip()
        assert _strip_pem_delimiters(end_only) == end_only.strip()

    def test_trailing_newlines_stripped_from_raw_input(self) -> None:
        """Raw license strings with trailing newlines from user paste are cleaned."""
        content = "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==\n\n"

        result = _strip_pem_delimiters(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_trailing_newlines_stripped_after_pem(self) -> None:
        """Inner content with trailing newlines after PEM stripping is cleaned."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==

-----END ONYX LICENSE-----"""

        result = _strip_pem_delimiters(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="
