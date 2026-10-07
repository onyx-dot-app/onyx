import pytest

from onyx.configs import app_configs
from onyx.oauth_provider.config import (
    canonical_mcp_resource,
    load_oauth_provider_settings,
    validate_oauth_url,
)
from onyx.oauth_provider.models import OAuthProviderSettings


def _patch_oauth_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    web_domain: str = "https://onyx.example",
) -> None:
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", web_domain)
    monkeypatch.setattr(app_configs, "OAUTH_PROVIDER_ENABLED", True)


def test_load_oauth_provider_settings_derives_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(monkeypatch, web_domain="https://onyx.example/")

    settings = load_oauth_provider_settings()
    assert settings is not None

    assert settings == OAuthProviderSettings(
        issuer_url="https://onyx.example/api/oauth-provider",
        mcp_resource_url="https://onyx.example/mcp/",
        web_url="https://onyx.example",
        web_origin="https://onyx.example",
    )


def test_load_oauth_provider_settings_preserves_web_path_and_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(monkeypatch, web_domain="https://onyx.example/app/")

    settings = load_oauth_provider_settings()
    assert settings is not None

    assert settings.issuer_url == "https://onyx.example/app/api/oauth-provider"
    assert settings.mcp_resource_url == "https://onyx.example/app/mcp/"
    assert settings.web_url == "https://onyx.example/app"
    assert settings.web_origin == "https://onyx.example"


def test_load_oauth_provider_settings_uses_any_url_canonical_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(monkeypatch, web_domain="HTTPS://Onyx.EXAMPLE:443/App/")

    settings = load_oauth_provider_settings()
    assert settings is not None

    assert settings.issuer_url == "https://onyx.example/App/api/oauth-provider"
    assert settings.mcp_resource_url == "https://onyx.example/App/mcp/"
    assert settings.web_url == "https://onyx.example/App"
    assert settings.web_origin == "https://onyx.example"


def test_load_oauth_provider_settings_is_off_without_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(monkeypatch)
    monkeypatch.setattr(app_configs, "OAUTH_PROVIDER_ENABLED", False)

    assert load_oauth_provider_settings() is None


@pytest.mark.parametrize(
    "web_domain",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
    ],
)
def test_load_oauth_provider_settings_allows_loopback_http(
    monkeypatch: pytest.MonkeyPatch, web_domain: str
) -> None:
    _patch_oauth_config(monkeypatch, web_domain=web_domain)

    settings = load_oauth_provider_settings()
    assert settings is not None

    assert settings.web_url == web_domain


@pytest.mark.parametrize(
    "web_domain",
    [
        "http://example.com",
        "https://",
        "https://user:pass@example.com",
        "https://*.example.com",
        "https://example.*",
        "https://example.com/path?query=1",
        "https://example.com?",
        "https://example.com/path#fragment",
        "https://example.com/path#",
        "https://example.com:bad",
        "https://exa mple.com",
        "https://example.com/*/path",
        " https://example.com",
        "https://example.com ",
        "https://example.com/\nnext",
        "https://example.com/" + ("a" * 2048),
    ],
)
def test_load_oauth_provider_settings_is_off_for_an_unusable_web_domain(
    monkeypatch: pytest.MonkeyPatch, web_domain: str
) -> None:
    _patch_oauth_config(monkeypatch, web_domain=web_domain)

    assert load_oauth_provider_settings() is None


def test_canonical_mcp_resource_accepts_exact_and_missing_final_slash_only() -> None:
    settings = OAuthProviderSettings(
        issuer_url="https://onyx.example/api/oauth-provider",
        mcp_resource_url="https://onyx.example/mcp/",
        web_url="https://onyx.example",
        web_origin="https://onyx.example",
    )

    assert canonical_mcp_resource("https://onyx.example/mcp/", settings) == (
        "https://onyx.example/mcp/"
    )
    assert canonical_mcp_resource("https://onyx.example/mcp", settings) == (
        "https://onyx.example/mcp/"
    )


@pytest.mark.parametrize(
    "resource",
    [
        "https://onyx.example/mcp/extra",
        "https://onyx.example/mcp?x=1",
        "https://onyx.example/mcp/#fragment",
        "https://onyx.example/mcp%2F",
        "https://onyx.example/MCP/",
        "https://ONYX.example/mcp/",
        "https://onyx.example:443/mcp/",
        "https://evil.example/mcp/",
        "https://onyx.example/mc",
    ],
)
def test_canonical_mcp_resource_rejects_prefix_widening(resource: str) -> None:
    settings = OAuthProviderSettings(
        issuer_url="https://onyx.example/api/oauth-provider",
        mcp_resource_url="https://onyx.example/mcp/",
        web_url="https://onyx.example",
        web_origin="https://onyx.example",
    )

    with pytest.raises(ValueError, match="Invalid OAuth provider resource"):
        canonical_mcp_resource(resource, settings)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://client.example/callback",
        "https://client.example/callback?code=abc&state=xyz",
        "http://localhost:3000/callback",
        "http://127.0.0.1:3000/callback",
        "http://[::1]:3000/callback",
    ],
)
def test_validate_oauth_url_accepts_strict_public_redirects(
    redirect_uri: str,
) -> None:
    assert validate_oauth_url(redirect_uri, allow_query=True) == str(redirect_uri)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://client.example/callback",
        "https://",
        "https://user:pass@client.example/callback",
        "https://*.example.com/callback",
        "https://client.example/*/callback",
        "https://client.example/callback#fragment",
        "https://client.example/callback#",
        "https://client.example:bad/callback",
        "https://client.example/call back",
        " https://client.example/callback",
        "https://client.example/callback ",
        "https://client.example/callback\nnext",
        "https://client.example/" + ("a" * 2048),
    ],
)
def test_validate_oauth_url_rejects_unsafe_redirects(
    redirect_uri: str,
) -> None:
    with pytest.raises(ValueError, match="Invalid OAuth provider URL"):
        validate_oauth_url(redirect_uri, allow_query=True)
