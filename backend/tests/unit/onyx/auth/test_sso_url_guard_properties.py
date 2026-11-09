"""Property tests for the IdP URL guard: a tenant admin chooses every character
of the URL, and the HTTP client, not the guard, decides which host it fetches."""

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from onyx.auth.sso_url_guard import UnsafeSSOUrl, validate_idp_url
from onyx.server.security.models import SSRFProtectionLevel

_PUBLIC_IP = "93.184.216.34"
# What the fake DNS answers for each name, with or without a trailing dot.
_DNS = {
    "public.example": _PUBLIC_IP,
    "localhost": "127.0.0.1",
    "internal.example": "10.0.0.1",
    "imds.example": "169.254.169.254",
    "metadata.google.internal": "169.254.169.254",
}

_AWS_IPV6_METADATA = ipaddress.ip_address("fd00:ec2::254")

_AddrInfo = list[
    tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]
]


def _resolve(host: str) -> str:
    """The address a client reaches for `host`, as the C resolver reads it:
    IDNA first (Python encodes str hosts so), then IP literals in every form
    that inet_aton accepts, then the fake DNS."""
    try:
        name = host.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise socket.gaierror(str(error)) from error
    try:
        return str(ipaddress.ip_address(name.strip("[]")))
    except ValueError:
        pass
    try:
        return socket.inet_ntoa(socket.inet_aton(name))
    except OSError:
        pass
    address = _DNS.get(name.removesuffix("."))
    if address is None:
        raise socket.gaierror(f"unknown host {host!r}")
    return address


def _getaddrinfo(host: str, port: object = None, *_: object, **__: object) -> _AddrInfo:
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (_resolve(host), port if isinstance(port, int) else 0),
        )
    ]


@contextmanager
def _guarded(level: SSRFProtectionLevel) -> Iterator[None]:
    security = MagicMock()
    security.ssrf_protection_level = level
    with (
        patch("onyx.auth.sso_url_guard.get_security_settings", return_value=security),
        patch("onyx.utils.url.socket.getaddrinfo", _getaddrinfo),
    ):
        yield


def _passes(url: str, level: SSRFProtectionLevel) -> bool:
    with _guarded(level):
        try:
            validate_idp_url(url, field="openid_config_url")
        except UnsafeSSOUrl:
            return False
    return True


def _client_targets(url: str) -> list[str]:
    """The address that httpx connects to for `url`. httpx fetches the OIDC
    discovery document, its endpoints and the refresh token endpoint; the JWT
    key fetch uses ssrf_safe_get, which checks the URL again itself. A URL that
    httpx cannot parse, or would not fetch over https, reaches nothing."""
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, UnicodeError, ValueError):
        return []
    if parsed.scheme != "https" or not parsed.host:
        return []
    try:
        return [_resolve(parsed.host)]
    except socket.gaierror:
        return []


def _blocked(address: str, level: SSRFProtectionLevel) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Cloud metadata stays blocked at every level. The AWS IPv6 metadata
    # address is private, not link-local.
    always_blocked = ip.is_link_local or ip.is_unspecified or ip == _AWS_IPV6_METADATA
    if level == SSRFProtectionLevel.DISABLED:
        return always_blocked
    if level == SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK:
        return always_blocked or ip.is_loopback
    return not ip.is_global or ip.is_multicast


_INTERNAL_HOSTS = [
    "127.0.0.1",
    "127.1",
    "2130706433",
    "0x7f000001",
    "0x7f.0.0.1",
    "0177.0.0.1",
    "017700000001",
    "0",
    "0.0.0.0",
    "127.0.0.1.",
    "[::1]",
    "[::]",
    "[::ffff:127.0.0.1]",
    "[::ffff:7f00:1]",
    "[0:0:0:0:0:ffff:127.0.0.1]",
    "[fe80::1%25eth0]",
    "[fd00:ec2::254]",
    "169.254.169.254",
    "10.0.0.1",
    "localhost",
    "LocalHost",
    "localhost.",
    "internal.example",
    "imds.example",
    "metadata.google.internal",
    # Full-width digits and a dot look-alike normalize to 127.0.0.1 under IDNA.
    "１２７.０.０.１",
    "127。0。0。1",
    "127%2E0%2E0%2E1",
    "%31%32%37.0.0.1",
    "locаlhost",
]
_PUBLIC_HOSTS = ["public.example", "PUBLIC.example", "public.example.", "8.8.8.8"]

_SCHEMES = ["https", "HTTPS", "hTTps", "http", "javascript", "file", "", " https"]
_SEPARATORS = ["://", ":/", ":///", ":\\\\", "://\\", ":"]
_USERINFO = ["", "public.example@", "user:pw@", "public.example%40", ":@", "@"]
_PORTS = ["", ":443", ":8443", ":0", ":65535", ":99999", ":", ":abc", ":4４３"]
_TAILS = [
    "",
    "/",
    "/.well-known/openid-configuration",
    "?next=/x",
    "#frag",
    "/@127.0.0.1",
    "\\@127.0.0.1",
    "@127.0.0.1",
    "#@127.0.0.1",
    "?@127.0.0.1/",
]
_JUNK = ["", " ", "\t", "\n", "\r", "\x00", "\x0b", " ", "​", "%00", "%0a"]


@st.composite
def _tricky_url(draw: st.DrawFn) -> str:
    host = draw(st.sampled_from(_INTERNAL_HOSTS + _PUBLIC_HOSTS))
    url = (
        draw(st.sampled_from(_SCHEMES))
        + draw(st.sampled_from(_SEPARATORS))
        + draw(st.sampled_from(_USERINFO))
        + host
        + draw(st.sampled_from(_PORTS))
        + draw(st.sampled_from(_TAILS))
    )
    # Junk at any place, as an admin can paste it.
    for _ in range(draw(st.integers(0, 2))):
        at = draw(st.integers(0, len(url)))
        url = url[:at] + draw(st.sampled_from(_JUNK)) + url[at:]
    return url


_LEVELS = st.sampled_from(
    [
        SSRFProtectionLevel.VALIDATE_ALL,
        SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK,
        SSRFProtectionLevel.DISABLED,
    ]
)


@settings(max_examples=200, deadline=None, derandomize=True)
@given(url=_tricky_url(), level=_LEVELS)
# URLs that do not parse raise UnsafeSSOUrl, which callers catch.
@example(url="https://idp.example.com%40[::1]/", level=SSRFProtectionLevel.VALIDATE_ALL)
@example(url="https://[::1]\\@127.0.0.1/", level=SSRFProtectionLevel.VALIDATE_ALL)
def test_no_url_that_reaches_a_blocked_address_passes(
    url: str, level: SSRFProtectionLevel
) -> None:
    if not _passes(url, level):
        return

    for address in _client_targets(url):
        assert not _blocked(address, level), (url, address)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(
    host=st.sampled_from(_PUBLIC_HOSTS),
    port=st.sampled_from(["", ":443", ":8443"]),
    path=st.lists(st.text("abcxyz0129-._~", min_size=1, max_size=6), max_size=3).map(
        lambda parts: "/" + "/".join(parts)
    ),
    query=st.sampled_from(["", "?a=1", "?next=%2Fhome&x=y"]),
    level=_LEVELS,
)
@example(
    host="8.8.8.8",
    port="",
    path="/.well-known/openid-configuration",
    query="",
    level=SSRFProtectionLevel.VALIDATE_ALL,
)
def test_ordinary_public_https_urls_pass(
    host: str, port: str, path: str, query: str, level: SSRFProtectionLevel
) -> None:
    assert _passes(f"https://{host}{port}{path}{query}", level)


@pytest.mark.parametrize("host", _INTERNAL_HOSTS)
def test_every_internal_host_is_blocked_in_its_plain_form(host: str) -> None:
    # Keeps the generator honest: each internal host form is rejected, and any
    # address that httpx reaches for it is internal.
    targets = _client_targets(f"https://{host}/")
    assert targets == [] or any(
        _blocked(address, SSRFProtectionLevel.VALIDATE_ALL) for address in targets
    )
    assert not _passes(f"https://{host}/", SSRFProtectionLevel.VALIDATE_ALL)


@pytest.mark.parametrize("host", ["169.254.169.254", "[fd00:ec2::254]"])
@pytest.mark.parametrize(
    "level",
    [SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK, SSRFProtectionLevel.DISABLED],
)
def test_cloud_metadata_is_blocked_at_relaxed_levels(
    host: str, level: SSRFProtectionLevel
) -> None:
    url = f"https://{host}/"
    targets = _client_targets(url)
    assert targets and all(_blocked(address, level) for address in targets)
    assert not _passes(url, level)
