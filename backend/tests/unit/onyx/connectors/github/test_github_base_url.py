from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.utils import normalize_github_base_url
from onyx.server.security.models import SSRFProtectionLevel

PUBLIC_IP = "93.184.216.34"


@contextmanager
def _ssrf_env(
    level: SSRFProtectionLevel = SSRFProtectionLevel.VALIDATE_ALL,
    resolves_to: str = PUBLIC_IP,
) -> Iterator[None]:
    """Pin the SSRF policy and DNS so these tests never touch the network."""
    with patch("onyx.connectors.github.utils.get_security_settings") as settings:
        settings.return_value.ssrf_protection_level = level
        with patch("onyx.utils.url.socket.getaddrinfo") as getaddrinfo:
            getaddrinfo.return_value = [(2, 1, 6, "", (resolves_to, 443))]
            yield


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        # bare host gets the scheme and the GHES API root
        ("github.example.com", "https://github.example.com/api/v3"),
        ("https://github.example.com", "https://github.example.com/api/v3"),
        ("https://github.example.com/", "https://github.example.com/api/v3"),
        ("  https://github.example.com  ", "https://github.example.com/api/v3"),
        # an explicit API root is left alone
        ("https://github.example.com/api/v3", "https://github.example.com/api/v3"),
        ("https://github.example.com/api/v3/", "https://github.example.com/api/v3"),
        # non-standard paths and ports are preserved
        ("https://example.com/github/api/v3", "https://example.com/github/api/v3"),
        ("https://github.example.com:8443", "https://github.example.com:8443/api/v3"),
    ],
)
def test_normalize_github_base_url(raw: str | None, expected: str | None) -> None:
    assert normalize_github_base_url(raw) == expected


def test_normalize_github_base_url_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        normalize_github_base_url("https://")


def _base_url_of(connector: GithubConnector) -> str:
    assert connector.github_client is not None
    return connector.github_client.requester.base_url


def _connector() -> GithubConnector:
    return GithubConnector(repo_owner="onyx-dot-app", repositories="onyx")


def test_credential_base_url_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.github.connector.GITHUB_CONNECTOR_BASE_URL", None
    )
    connector = _connector()
    with _ssrf_env():
        connector.load_credentials(
            {
                "github_access_token": "token",
                "github_base_url": "https://github.example.com",
            }
        )
    assert _base_url_of(connector) == "https://github.example.com/api/v3"


def test_credential_base_url_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.github.connector.GITHUB_CONNECTOR_BASE_URL",
        "https://from-env.example.com/api/v3",
    )
    connector = _connector()
    with _ssrf_env():
        connector.load_credentials(
            {
                "github_access_token": "token",
                "github_base_url": "https://from-cred.example.com",
            }
        )
    assert _base_url_of(connector) == "https://from-cred.example.com/api/v3"


@pytest.mark.parametrize("cred_value", [None, "", "   "])
def test_env_base_url_is_the_fallback(
    monkeypatch: pytest.MonkeyPatch, cred_value: str | None
) -> None:
    """Existing GHES deployments set only the env var and must keep working."""
    monkeypatch.setattr(
        "onyx.connectors.github.connector.GITHUB_CONNECTOR_BASE_URL",
        "https://from-env.example.com/api/v3",
    )
    connector = _connector()
    with _ssrf_env():
        connector.load_credentials(
            {"github_access_token": "token", "github_base_url": cred_value}
        )
    assert _base_url_of(connector) == "https://from-env.example.com/api/v3"


def test_defaults_to_github_dot_com(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.github.connector.GITHUB_CONNECTOR_BASE_URL", None
    )
    connector = _connector()
    with _ssrf_env():
        connector.load_credentials({"github_access_token": "token"})
    assert _base_url_of(connector) == "https://api.github.com"


class TestCredentialBaseUrlSSRF:
    """The credential base URL is admin-supplied and PyGithub sends the access
    token to whatever host it names, so it is an SSRF and token-leak surface."""

    def _load(
        self,
        url: str,
        level: SSRFProtectionLevel = SSRFProtectionLevel.VALIDATE_ALL,
        resolves_to: str = PUBLIC_IP,
    ) -> None:
        connector = _connector()
        with _ssrf_env(level=level, resolves_to=resolves_to):
            connector.load_credentials(
                {"github_access_token": "token", "github_base_url": url}
            )

    @pytest.mark.parametrize(
        "url",
        [
            "http://github.example.com",  # plaintext would leak the token
            "https://10.0.0.1",  # RFC1918
            "https://192.168.1.1",
            "https://127.0.0.1",  # loopback
            "https://169.254.169.254",  # cloud metadata
            "https://[::1]",
            "https://metadata.google.internal",
            "https://kubernetes.default.svc",
            "https://localhost",
        ],
    )
    def test_blocks_internal_targets(self, url: str) -> None:
        with pytest.raises(ConnectorValidationError):
            self._load(url)

    def test_blocks_embedded_credentials(self) -> None:
        with pytest.raises(ConnectorValidationError):
            self._load("https://user:pass@github.example.com")

    def test_blocks_hostname_that_resolves_to_a_private_ip(self) -> None:
        """A public-looking name pointed at internal space is the real attack;
        a hostname pattern check would not catch this."""
        with pytest.raises(ConnectorValidationError):
            self._load("https://github.example.com", resolves_to="10.0.0.1")

    def test_allows_a_public_enterprise_server(self) -> None:
        self._load("https://github.example.com")

    def test_private_server_allowed_when_admin_relaxes_the_level(self) -> None:
        """Self-hosted Onyx usually reaches Enterprise Server over the LAN."""
        self._load("https://10.0.0.1", level=SSRFProtectionLevel.VALIDATE_LLM)

    def test_metadata_stays_blocked_even_when_relaxed(self) -> None:
        """Allowing the LAN must not open up the cloud metadata endpoint."""
        with pytest.raises(ConnectorValidationError):
            self._load(
                "https://169.254.169.254", level=SSRFProtectionLevel.VALIDATE_LLM
            )

    def test_env_var_is_not_ssrf_checked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GITHUB_CONNECTOR_BASE_URL is deployment config, not user input.
        Existing self-hosted Enterprise Server installs must keep working."""
        monkeypatch.setattr(
            "onyx.connectors.github.connector.GITHUB_CONNECTOR_BASE_URL",
            "https://10.0.0.1/api/v3",
        )
        connector = _connector()
        with _ssrf_env():
            connector.load_credentials({"github_access_token": "token"})
        assert _base_url_of(connector) == "https://10.0.0.1/api/v3"
