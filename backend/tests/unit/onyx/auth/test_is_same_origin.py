import pytest

from onyx.auth.users import _is_same_origin


class TestExactMatch:
    """Origins that are textually identical should always match."""

    @pytest.mark.parametrize(
        "origin",
        [
            "http://localhost:3000",
            "https://app.example.com",
            "https://app.example.com:8443",
            "http://127.0.0.1:8080",
        ],
    )
    def test_identical_origins(self, origin: str) -> None:
        assert _is_same_origin(origin, origin)


class TestLoopbackPortRelaxation:
    """On loopback addresses, port differences should be ignored."""

    @pytest.mark.parametrize(
        "actual,expected",
        [
            ("http://localhost:3001", "http://localhost:3000"),
            ("http://localhost:8080", "http://localhost:3000"),
            ("http://localhost", "http://localhost:3000"),
            ("http://127.0.0.1:3001", "http://127.0.0.1:3000"),
            ("http://[::1]:3001", "http://[::1]:3000"),
        ],
    )
    def test_loopback_different_ports_accepted(
        self, actual: str, expected: str
    ) -> None:
        assert _is_same_origin(actual, expected)

    @pytest.mark.parametrize(
        "actual,expected",
        [
            ("https://localhost:3001", "http://localhost:3000"),
            ("http://localhost:3001", "https://localhost:3000"),
        ],
    )
    def test_loopback_different_scheme_rejected(
        self, actual: str, expected: str
    ) -> None:
        assert not _is_same_origin(actual, expected)

    def test_loopback_hostname_mismatch_rejected(self) -> None:
        assert not _is_same_origin("http://localhost:3001", "http://127.0.0.1:3000")


class TestNonLoopbackStrictPort:
    """Non-loopback origins must match scheme, hostname, AND port."""

    def test_different_port_rejected(self) -> None:
        assert not _is_same_origin(
            "https://app.example.com:8443", "https://app.example.com"
        )

    def test_different_hostname_rejected(self) -> None:
        assert not _is_same_origin("https://evil.com", "https://app.example.com")

    def test_different_scheme_rejected(self) -> None:
        assert not _is_same_origin("http://app.example.com", "https://app.example.com")

    def test_same_port_explicit(self) -> None:
        assert _is_same_origin(
            "https://app.example.com:443", "https://app.example.com:443"
        )


class TestDefaultPortNormalization:
    """Port should be normalized so that omitted default port == explicit default port."""

    def test_http_implicit_vs_explicit_80(self) -> None:
        assert _is_same_origin("http://example.com", "http://example.com:80")

    def test_http_explicit_80_vs_implicit(self) -> None:
        assert _is_same_origin("http://example.com:80", "http://example.com")

    def test_https_implicit_vs_explicit_443(self) -> None:
        assert _is_same_origin("https://example.com", "https://example.com:443")

    def test_https_explicit_443_vs_implicit(self) -> None:
        assert _is_same_origin("https://example.com:443", "https://example.com")

    def test_http_non_default_port_vs_implicit_rejected(self) -> None:
        assert not _is_same_origin("http://example.com:8080", "http://example.com")


class TestTrailingSlash:
    """Trailing slashes should not affect comparison."""

    def test_trailing_slash_on_actual(self) -> None:
        assert _is_same_origin("https://app.example.com/", "https://app.example.com")

    def test_trailing_slash_on_expected(self) -> None:
        assert _is_same_origin("https://app.example.com", "https://app.example.com/")

    def test_trailing_slash_on_both(self) -> None:
        assert _is_same_origin("https://app.example.com/", "https://app.example.com/")


class TestCSWSHScenarios:
    """Realistic attack scenarios that must be rejected."""

    def test_remote_attacker_rejected(self) -> None:
        assert not _is_same_origin("https://evil.com", "http://localhost:3000")

    def test_remote_attacker_same_port_rejected(self) -> None:
        assert not _is_same_origin("http://evil.com:3000", "http://localhost:3000")

    def test_remote_attacker_matching_hostname_different_port(self) -> None:
        assert not _is_same_origin(
            "https://app.example.com:9999", "https://app.example.com"
        )
