"""Constrains the IdP URLs the server fetches on an admin's behalf.

An OIDC provider's discovery URL is fetched server-side, and the document it
returns names the token and userinfo endpoints fetched after it. On a self-hosted
box that is the operator's own network. On cloud it is Onyx reaching into its own,
so those URLs are held to the public internet.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from shared_configs.configs import MULTI_TENANT

_REQUIRED_SCHEME = "https"


class UnsafeSSOUrl(ValueError):
    """The URL names somewhere the server must not fetch on request."""


_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# is_global already rejects loopback, private, link-local, NAT64 (via the ::/8
# reserved block), and IPv4-mapped (it judges the embedded address). IPv6
# site-local is the one private range it still reports as global.
_SITE_LOCAL_V6 = ipaddress.IPv6Network("fec0::/10")


def _parse_address(value: str) -> _IPAddress | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_public_unicast(ip: _IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip in _SITE_LOCAL_V6:
        return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def _reject_private_host(host: str) -> None:
    literal = _parse_address(host)
    if literal is not None:
        if not _is_public_unicast(literal):
            raise UnsafeSSOUrl(f"{host} is not a public address")
        return

    # Resolution here and at fetch time are separate lookups, so this raises the
    # cost of pointing at a private address rather than making it impossible.
    # Closing the rebinding gap needs a transport pinned to the vetted address.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeSSOUrl(f"{host} could not be resolved") from e

    for address in {info[4][0] for info in infos if isinstance(info[4][0], str)}:
        resolved = _parse_address(address)
        if resolved is not None and not _is_public_unicast(resolved):
            raise UnsafeSSOUrl(
                f"{host} resolves to {address}, which is not a public address"
            )


def validate_idp_url(url: str, *, field: str) -> None:
    """Reject a URL a multi-tenant deployment must not fetch off the public
    internet. Resolves the host, so it does blocking DNS and any redirect-
    following fetcher must apply it per hop rather than once.
    """
    if not MULTI_TENANT:
        return

    parts = urlsplit(url)
    if parts.scheme.lower() != _REQUIRED_SCHEME:
        raise UnsafeSSOUrl(f"{field} must be an https URL")
    if parts.username or parts.password:
        raise UnsafeSSOUrl(f"{field} must not carry credentials")

    host = parts.hostname
    if not host:
        raise UnsafeSSOUrl(f"{field} must name a host")
    _reject_private_host(host)


def validate_discovered_endpoints(
    discovery_document: dict[str, object] | None,
) -> None:
    """The discovery document is attacker-chosen once its URL is, so the
    endpoints Onyx goes on to call get the same treatment as the URL itself.
    A document with no endpoints names nothing to fetch."""
    if not MULTI_TENANT or not discovery_document:
        return

    for field in (
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
    ):
        endpoint = discovery_document.get(field)
        if isinstance(endpoint, str) and endpoint:
            validate_idp_url(endpoint, field=field)
