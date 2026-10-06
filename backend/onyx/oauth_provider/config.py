from urllib.parse import urlsplit

from pydantic import AnyUrl, BaseModel, ConfigDict

from onyx.configs import app_configs

_MAX_URL_LENGTH = 2048
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OAuthProviderSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer_url: str
    mcp_resource_url: str
    web_url: str
    web_origin: str


def _validate_url(value: str, *, allow_query: bool) -> str:
    try:
        split = urlsplit(value)
        hostname = split.hostname
        if (
            len(value) <= _MAX_URL_LENGTH
            and not any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in value)
            and "*" not in value
            and "#" not in value
            and hostname is not None
            and split.username is None
            and split.password is None
            and (allow_query or "?" not in value)
            and (
                split.scheme == "https"
                or (split.scheme == "http" and hostname in _LOOPBACK_HOSTS)
            )
        ):
            return str(AnyUrl(value))
    except ValueError:
        pass
    raise ValueError("Invalid OAuth provider URL")


def get_oauth_provider_settings() -> OAuthProviderSettings:
    web_url = _validate_url(app_configs.WEB_DOMAIN, allow_query=False).rstrip("/")
    resource_url = (
        app_configs.MCP_SERVER_OAUTH_RESOURCE_URL or f"{web_url}/mcp"
    ).rstrip("/") + "/"
    split = urlsplit(web_url)
    return OAuthProviderSettings(
        issuer_url=f"{web_url}/api/oauth-provider",
        mcp_resource_url=_validate_url(resource_url, allow_query=False),
        web_url=web_url,
        web_origin=f"{split.scheme}://{split.netloc}",
    )


def canonical_mcp_resource(value: str, settings: OAuthProviderSettings) -> str:
    if value not in (settings.mcp_resource_url, settings.mcp_resource_url.rstrip("/")):
        raise ValueError("Invalid OAuth provider resource")
    return settings.mcp_resource_url


def validate_oauth_redirect_uri(value: str) -> str:
    return _validate_url(value, allow_query=True)
