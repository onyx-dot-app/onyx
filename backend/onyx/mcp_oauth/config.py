from typing import NoReturn
from urllib.parse import urlsplit

from pydantic import AnyUrl, BaseModel, ConfigDict, ValidationError

from onyx.configs import app_configs

_MAX_URL_LENGTH = 2048
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class MCPOAuthSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    issuer_url: str
    resource_url: str
    web_url: str
    web_origin: str


def _raise_invalid_url() -> NoReturn:
    raise ValueError("Invalid MCP OAuth URL")


def _has_control_char(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _has_whitespace(value: str) -> bool:
    return any(char.isspace() for char in value)


def _validate_common_url(
    value: str,
    *,
    allow_query: bool,
    require_trailing_slash: bool = False,
) -> str:
    if len(value) > _MAX_URL_LENGTH:
        _raise_invalid_url()
    if (
        value != value.strip()
        or _has_control_char(value)
        or _has_whitespace(value)
        or "*" in value
        or "#" in value
    ):
        _raise_invalid_url()

    try:
        split = urlsplit(value)
        _port = split.port
    except ValueError:
        _raise_invalid_url()

    hostname = split.hostname
    if hostname is None:
        _raise_invalid_url()
    if split.username is not None or split.password is not None:
        _raise_invalid_url()
    if split.fragment or (split.query and not allow_query):
        _raise_invalid_url()
    if require_trailing_slash and not split.path.endswith("/"):
        _raise_invalid_url()

    hostname = hostname.lower()
    scheme = split.scheme.lower()
    if scheme == "https" or (scheme == "http" and hostname in _LOOPBACK_HOSTS):
        try:
            return str(AnyUrl(value))
        except ValidationError:
            _raise_invalid_url()
    _raise_invalid_url()


def _canonical_origin(value: str) -> str:
    split = urlsplit(value)
    return f"{split.scheme}://{split.netloc}"


def _canonical_resource_url(value: str) -> str:
    resource_url = value.rstrip("/") + "/"
    return _validate_common_url(
        resource_url,
        allow_query=False,
        require_trailing_slash=True,
    )


def get_mcp_oauth_settings() -> MCPOAuthSettings:
    web_url = _validate_common_url(app_configs.WEB_DOMAIN, allow_query=False).rstrip(
        "/"
    )
    issuer_url = _validate_common_url(f"{web_url}/api/mcp-oauth", allow_query=False)
    resource_url = _canonical_resource_url(
        app_configs.MCP_SERVER_OAUTH_RESOURCE_URL or f"{web_url}/mcp"
    )

    return MCPOAuthSettings(
        enabled=app_configs.MCP_SERVER_OAUTH_ENABLED,
        issuer_url=issuer_url,
        resource_url=resource_url,
        web_url=web_url,
        web_origin=_canonical_origin(web_url),
    )


def canonical_mcp_resource(value: str, settings: MCPOAuthSettings) -> str:
    if value == settings.resource_url:
        return settings.resource_url
    if value == settings.resource_url.rstrip("/"):
        return settings.resource_url
    raise ValueError("Invalid MCP OAuth resource")


def validate_mcp_redirect_uri(value: str) -> str:
    _validate_common_url(value, allow_query=True)
    try:
        return str(AnyUrl(value))
    except ValidationError:
        _raise_invalid_url()
