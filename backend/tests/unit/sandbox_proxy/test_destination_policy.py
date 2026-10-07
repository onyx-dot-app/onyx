import ipaddress
import socket

import pytest

from onyx.sandbox_proxy.destination_policy import (
    is_destination_blocked,
    parse_destination_policy,
    resolve_destination,
)


@pytest.mark.parametrize(
    "address",
    ["8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"],
)
def test_public_address_preserves_route(address: str) -> None:
    assert resolve_destination(parse_destination_policy(""), address, 443) == (
        str(ipaddress.ip_address(address)),
    )


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:10.0.0.1",
        "64:ff9b::a00:1",
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
    ],
)
def test_internal_address_is_blocked(address: str) -> None:
    assert is_destination_blocked(parse_destination_policy(""), address, 443)


@pytest.mark.parametrize(
    "cidr,address",
    [
        ("8.8.8.0/24", "8.8.8.8"),
        ("2600:ffff:ffff::/64", "2600:ffff:ffff::99"),
        ("8.8.8.0/24", "::ffff:8.8.8.8"),
        ("8.8.8.0/24", "64:ff9b::808:808"),
        ("::ffff:0:0/96", "::ffff:8.8.8.8"),
        ("64:ff9b::/96", "64:ff9b::808:808"),
    ],
)
def test_internal_cidrs_cover_original_and_embedded_addresses(
    cidr: str, address: str
) -> None:
    assert is_destination_blocked(
        parse_destination_policy("", [f" {cidr} "]), address, 443
    )


@pytest.mark.parametrize("cidr", ["invalid", "", "10.0.0.1/24", "2600:ffff::1/64"])
def test_invalid_internal_cidr_fails_at_startup(cidr: str) -> None:
    with pytest.raises(ValueError):
        parse_destination_policy("", [cidr])


def _mock_dns(
    monkeypatch: pytest.MonkeyPatch,
    addresses: list[str],
    *,
    expected_host: str = "service.example",
) -> None:
    def resolve(
        host: str, port: int, *, family: int, type: int, proto: int
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert host == expected_host
        assert family == socket.AF_UNSPEC
        assert type == socket.SOCK_STREAM
        assert proto == socket.IPPROTO_TCP
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
            for address in addresses
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def test_public_dns_preserves_all_validated_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_dns(monkeypatch, ["2606:4700:4700::1111", "8.8.8.8"])
    assert resolve_destination(
        parse_destination_policy(""), " SERVICE.EXAMPLE ", 443
    ) == (
        "2606:4700:4700::1111",
        "8.8.8.8",
    )


@pytest.mark.parametrize(
    "addresses",
    [[], ["8.8.8.8", "10.0.0.1"], ["10.0.0.1", "8.8.8.8"], ["invalid"]],
)
def test_empty_invalid_or_mixed_dns_fails_closed(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str]
) -> None:
    _mock_dns(monkeypatch, addresses)
    assert is_destination_blocked(parse_destination_policy(""), "service.example", 443)


def test_dns_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise socket.gaierror("unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert is_destination_blocked(
        parse_destination_policy("http://service.example"), "service.example", 80
    )


@pytest.mark.parametrize(
    "host,port", [("", 443), (" ", 443), ("8.8.8.8", 0), ("8.8.8.8", 65536)]
)
def test_invalid_destination_fails_closed(host: str, port: int) -> None:
    assert is_destination_blocked(parse_destination_policy(""), host, port)


def test_api_exception_requires_exact_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_dns(monkeypatch, ["2600:ffff:ffff::99"])
    policy = parse_destination_policy(
        "https://service.example/api", ["2600:ffff:ffff::/64"]
    )
    assert resolve_destination(policy, "service.example", 443) == (
        "2600:ffff:ffff::99",
    )
    assert is_destination_blocked(policy, "service.example", 80)
    assert is_destination_blocked(policy, "2600:ffff:ffff::99", 443)


def test_internal_cidr_blocks_mixed_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_dns(monkeypatch, ["8.8.8.8", "2600:ffff:ffff::99"])
    assert is_destination_blocked(
        parse_destination_policy("", ["2600:ffff:ffff::/64"]), "service.example", 443
    )


def test_api_exception_does_not_allow_dns_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_dns(monkeypatch, ["10.0.0.1"], expected_host="alias.example")
    assert is_destination_blocked(
        parse_destination_policy("http://service.example"), "alias.example", 80
    )


@pytest.mark.parametrize(
    "url,port",
    [
        ("http://10.0.0.1/api", 80),
        ("https://10.0.0.1/api", 443),
        ("http://10.0.0.1:8080/api", 8080),
        ("http://[2600:ffff:ffff::99]:8080/api", 8080),
    ],
)
def test_api_exception_supports_default_and_explicit_ports(url: str, port: int) -> None:
    host = "2600:ffff:ffff::99" if "[" in url else "10.0.0.1"
    policy = parse_destination_policy(url, ["2600:ffff:ffff::/64"])
    assert resolve_destination(policy, host, port) == (host,)
    assert is_destination_blocked(policy, host, port + 1)
