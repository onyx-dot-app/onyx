"""Stop a tenant admin from aiming the OIDC discovery URL, or the endpoints it
names, at an address the server should not fetch."""

from urllib.parse import urlsplit

from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.url import SSRFException, validate_outbound_http_url

_DISCOVERY_ENDPOINT_FIELDS = (
    "authorization_endpoint",
    "token_endpoint",
    "userinfo_endpoint",
    "jwks_uri",
)


class UnsafeSSOUrl(ValueError):
    """The URL names somewhere the server must not fetch on request."""


def validate_idp_url(url: str, *, field: str) -> None:
    """Require https, no embedded credentials, and an address the SSRF Protection
    setting permits. Checks one DNS resolution, so a redirect-following fetcher
    must re-check each hop."""
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise UnsafeSSOUrl(f"{field} must not carry credentials")

    params = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    try:
        validate_outbound_http_url(
            url,
            allow_private_network=params.allow_private_network,
            https_only=True,
            block_loopback_and_link_local=params.block_loopback_and_link_local,
            block_link_local_only=params.block_link_local_only,
        )
    except (SSRFException, ValueError) as e:
        raise UnsafeSSOUrl(f"{field}: {e}") from e


def validate_discovered_endpoints(
    discovery_document: dict[str, object] | None,
) -> None:
    """The document is attacker-controlled once its URL is, so guard every
    endpoint it names as strictly as the URL."""
    if not discovery_document:
        return
    for field in _DISCOVERY_ENDPOINT_FIELDS:
        endpoint = discovery_document.get(field)
        if isinstance(endpoint, str) and endpoint:
            validate_idp_url(endpoint, field=field)
