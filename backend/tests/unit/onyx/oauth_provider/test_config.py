import pytest

from onyx.configs import app_configs
from onyx.oauth_provider.config import (
    OAuthProviderSettings,
    canonical_mcp_resource,
    get_oauth_provider_settings,
    validate_oauth_redirect_uri,
)


def _patch_oauth_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    web_domain: str = "https://onyx.example",
    resource_url: str | None = None,
) -> None:
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", web_domain)
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", resource_url)


def test_get_oauth_provider_settings_derives_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(monkeypatch, web_domain="https://onyx.example/")

    settings = get_oauth_provider_settings()

    assert settings == OAuthProviderSettings(
        issuer_url="https://onyx.example/api/oauth-provider",
        mcp_resource_url="https://onyx.example/mcp/",
        web_url="https://onyx.example",
        web_origin="https://onyx.example",
    )


def test_get_oauth_provider_settings_preserves_web_path_and_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(monkeypatch, web_domain="https://onyx.example/app/")

    settings = get_oauth_provider_settings()

    assert settings.issuer_url == "https://onyx.example/app/api/oauth-provider"
    assert settings.mcp_resource_url == "https://onyx.example/app/mcp/"
    assert settings.web_url == "https://onyx.example/app"
    assert settings.web_origin == "https://onyx.example"


def test_get_oauth_provider_settings_uses_any_url_canonical_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_config(
        monkeypatch,
        web_domain="HTTPS://Onyx.EXAMPLE:443/App/",
        resource_url="HTTPS://MCP.EXAMPLE.com:443/Custom/Prefix////",
    )

    settings = get_oauth_provider_settings()

    assert settings.issuer_url == "https://onyx.example/App/api/oauth-provider"
    assert settings.mcp_resource_url == "https://mcp.example.com/Custom/Prefix/"
    assert settings.web_url == "https://onyx.example/App"
    assert settings.web_origin == "https://onyx.example"


@pytest.mark.parametrize(
    "resource_url",
    [
        "https://mcp.example.com",
        "https://mcp.example.com/",
        "https://mcp.example.com/custom/prefix",
        "https://mcp.example.com/custom/prefix/",
    ],
)
def test_get_oauth_provider_settings_canonicalizes_resource_trailing_slash(
    monkeypatch: pytest.MonkeyPatch, resource_url: str
) -> None:
    _patch_oauth_config(monkeypatch, resource_url=resource_url)

    settings = get_oauth_provider_settings()

    assert settings.mcp_resource_url == resource_url.rstrip("/") + "/"


@pytest.mark.parametrize(
    "web_domain",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
    ],
)
def test_get_oauth_provider_settings_allows_loopback_http(
    monkeypatch: pytest.MonkeyPatch, web_domain: str
) -> None:
    _patch_oauth_config(monkeypatch, web_domain=web_domain)

    settings = get_oauth_provider_settings()

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
def test_get_oauth_provider_settings_rejects_invalid_web_domain(
    monkeypatch: pytest.MonkeyPatch, web_domain: str
) -> None:
    _patch_oauth_config(
        monkeypatch, web_domain=web_domain, resource_url="https://mcp.example/mcp"
    )

    with pytest.raises(ValueError, match="Invalid OAuth provider URL"):
        get_oauth_provider_settings()


@pytest.mark.parametrize(
    "resource_url",
    [
        "http://mcp.example.com/mcp",
        "https://",
        "https://user:pass@mcp.example.com/mcp",
        "https://*.example.com/mcp",
        "https://mcp.example.com/*/mcp",
        "https://mcp.example.com/mcp?query=1",
        "https://mcp.example.com/mcp#fragment",
        "https://mcp.example.com/mcp#",
        "https://mcp.example.com:bad/mcp",
        "https://mcp.example.com/m cp",
        "https://mcp.example.com/mcp\nnext",
        "https://mcp.example.com/" + ("a" * 2048),
    ],
)
def test_get_oauth_provider_settings_rejects_invalid_resource_url(
    monkeypatch: pytest.MonkeyPatch, resource_url: str
) -> None:
    _patch_oauth_config(monkeypatch, resource_url=resource_url)

    with pytest.raises(ValueError, match="Invalid OAuth provider URL"):
        get_oauth_provider_settings()


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
def test_validate_mcp_redirect_uri_accepts_strict_public_redirects(
    redirect_uri: str,
) -> None:
    assert validate_oauth_redirect_uri(redirect_uri) == str(redirect_uri)


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
def test_validate_mcp_redirect_uri_rejects_unsafe_redirects(
    redirect_uri: str,
) -> None:
    with pytest.raises(ValueError, match="Invalid OAuth provider URL"):
        validate_oauth_redirect_uri(redirect_uri)
