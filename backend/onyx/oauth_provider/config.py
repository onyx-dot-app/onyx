import ipaddress
from urllib.parse import urlsplit

from pydantic import AnyUrl

from onyx.auth.constants import OAUTH_PROVIDER_MAX_URL_LENGTH
from onyx.configs import app_configs
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth_provider.models import OAuthProviderSettings
from onyx.utils.logger import setup_logger

logger = setup_logger()


def is_loopback_host(hostname: str | None) -> bool:
    """`localhost` or a loopback IP address (RFC 8252 7.3)."""
    if hostname is None:
        return False
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_oauth_url(value: str, *, allow_query: bool) -> str:
    """Return the canonical form of an OAuth URL, or raise ValueError.

    Requires HTTPS (plain HTTP only for loopback hosts) and rejects credentials,
    fragments, wildcards, whitespace and control characters."""
    try:
        split = urlsplit(value)
        hostname = split.hostname
        if (
            len(value) <= OAUTH_PROVIDER_MAX_URL_LENGTH
            and not any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in value)
            and "*" not in value
            and "#" not in value
            and hostname is not None
            and split.username is None
            and split.password is None
            and (allow_query or "?" not in value)
            and (
                split.scheme == "https"
                or (split.scheme == "http" and is_loopback_host(hostname))
            )
        ):
            return str(AnyUrl(value))
    except ValueError:
        pass
    raise ValueError("Invalid OAuth provider URL")


def load_oauth_provider_settings() -> OAuthProviderSettings | None:
    """Settings for the OAuth provider, or None when it cannot run: the flag is off,
    or `WEB_DOMAIN` is not HTTPS (plain HTTP only on a loopback host)."""
    if not app_configs.OAUTH_PROVIDER_ENABLED:
        return None
    try:
        web_url = validate_oauth_url(app_configs.WEB_DOMAIN, allow_query=False).rstrip(
            "/"
        )
    except ValueError:
        logger.warning(
            "OAuth provider is off: WEB_DOMAIN must be HTTPS, or HTTP on localhost"
        )
        return None
    split = urlsplit(web_url)
    return OAuthProviderSettings(
        issuer_url=f"{web_url}/api/oauth-provider",
        mcp_resource_url=f"{web_url}/mcp/",
        web_url=web_url,
        web_origin=f"{split.scheme}://{split.netloc}",
    )


OAUTH_PROVIDER_SETTINGS = load_oauth_provider_settings()


def require_oauth_provider_settings() -> OAuthProviderSettings:
    if OAUTH_PROVIDER_SETTINGS is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    return OAUTH_PROVIDER_SETTINGS


def canonical_mcp_resource(value: str, settings: OAuthProviderSettings) -> str:
    if value not in (settings.mcp_resource_url, settings.mcp_resource_url.rstrip("/")):
        raise ValueError("Invalid OAuth provider resource")
    return settings.mcp_resource_url
