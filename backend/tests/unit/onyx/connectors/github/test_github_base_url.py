import pytest

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.utils import normalize_github_base_url


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
    connector.load_credentials(
        {"github_access_token": "token", "github_base_url": cred_value}
    )
    assert _base_url_of(connector) == "https://from-env.example.com/api/v3"


def test_defaults_to_github_dot_com(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.github.connector.GITHUB_CONNECTOR_BASE_URL", None
    )
    connector = _connector()
    connector.load_credentials({"github_access_token": "token"})
    assert _base_url_of(connector) == "https://api.github.com"
