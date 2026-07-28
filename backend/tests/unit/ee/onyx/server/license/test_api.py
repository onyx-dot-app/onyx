"""Tests for license API utilities."""

from ee.onyx.server.license.api import _normalize_license_file


class TestNormalizeLicenseFile:
    """Reduces a .lic file to the bare base64 blob."""

    def test_strips_pem_delimiters(self) -> None:
        """Content wrapped in PEM delimiters is extracted correctly."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----"""

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_joins_wrapped_base64_into_one_line(self) -> None:
        """A wrapped file must collapse to a single line.

        The stored blob is later sent as a Bearer token, and a header value
        containing newlines is rejected before the request is sent.
        """
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjog
IjEuMCIsICJ0ZW5hbnRfaWQiOiAidGVz
dCJ9LCAic2lnbmF0dXJlIjogImFiYyJ9
-----END ONYX LICENSE-----"""

        result = _normalize_license_file(content)

        assert "\n" not in result
        assert result == (
            "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjog"
            "IjEuMCIsICJ0ZW5hbnRfaWQiOiAidGVz"
            "dCJ9LCAic2lnbmF0dXJlIjogImFiYyJ9"
        )

    def test_returns_unchanged_without_delimiters(self) -> None:
        """Content without PEM delimiters is returned unchanged."""
        content = "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

        result = _normalize_license_file(content)

        assert result == content

    def test_handles_whitespace(self) -> None:
        """Leading/trailing whitespace is handled correctly."""
        content = """
  -----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----
  """

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_partial_delimiters_keep_their_marker(self) -> None:
        """Only a matched pair is a license file, so a lone marker stays and
        the blob fails signature verification rather than being half-accepted.
        Whitespace still collapses, since that is unconditional."""
        begin_only = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="""

        end_only = """eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==
-----END ONYX LICENSE-----"""

        assert _normalize_license_file(begin_only) == "".join(begin_only.split())
        assert _normalize_license_file(end_only) == "".join(end_only.split())

    def test_trailing_newlines_stripped_from_raw_input(self) -> None:
        """Raw license strings with trailing newlines from user paste are cleaned."""
        content = "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==\n\n"

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="

    def test_trailing_newlines_stripped_after_pem(self) -> None:
        """Inner content with trailing newlines after PEM stripping is cleaned."""
        content = """-----BEGIN ONYX LICENSE-----
eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ==

-----END ONYX LICENSE-----"""

        result = _normalize_license_file(content)

        assert result == "eyJwYXlsb2FkIjogeyJ2ZXJzaW9uIjogIjEuMCJ9fQ=="
