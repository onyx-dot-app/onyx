from urllib.parse import urlsplit

from pydantic import AnyUrl, BaseModel, ConfigDict

from onyx.configs import app_configs

_MAX_URL_LENGTH = 2048
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class MCPOAuthSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer_url: str
    resource_url: str
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
            and (allow_query or not split.query)
            and (
                split.scheme == "https"
                or (split.scheme == "http" and hostname in _LOOPBACK_HOSTS)
            )
        ):
            return str(AnyUrl(value))
    except ValueError:
        pass
    raise ValueError("Invalid MCP OAuth URL")


def get_mcp_oauth_settings() -> MCPOAuthSettings:
    web_url = _validate_url(app_configs.WEB_DOMAIN, allow_query=False).rstrip("/")
    resource_url = (
        app_configs.MCP_SERVER_OAUTH_RESOURCE_URL or f"{web_url}/mcp"
    ).rstrip("/") + "/"
    split = urlsplit(web_url)
    return MCPOAuthSettings(
        issuer_url=f"{web_url}/api/mcp-oauth",
        resource_url=_validate_url(resource_url, allow_query=False),
        web_url=web_url,
        web_origin=f"{split.scheme}://{split.netloc}",
    )


def canonical_mcp_resource(value: str, settings: MCPOAuthSettings) -> str:
    if value not in (settings.resource_url, settings.resource_url.rstrip("/")):
        raise ValueError("Invalid MCP OAuth resource")
    return settings.resource_url


def validate_mcp_redirect_uri(value: str) -> str:
    return _validate_url(value, allow_query=True)
