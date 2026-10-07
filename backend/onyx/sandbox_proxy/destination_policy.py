"""Validate proxy destinations and pin connections to their approved addresses."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable, Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit

from onyx.sandbox_proxy.models import DestinationPolicyConfig, IPNetwork

if TYPE_CHECKING:
    from socket import _RetAddress

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_NAT64_NETWORK = ipaddress.IPv6Network("64:ff9b::/96")
_destination: ContextVar[tuple[str, int, tuple[str, ...]] | None] = ContextVar(
    "sandbox_proxy_destination", default=None
)


def _embedded_address(address: IPAddress) -> IPAddress:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return address.ipv4_mapped
        if address in _NAT64_NETWORK:
            return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address


def parse_destination_policy(
    api_url: str, internal_cidrs: Iterable[str] = ()
) -> DestinationPolicyConfig:
    networks: tuple[IPNetwork, ...] = tuple(
        ipaddress.ip_network(cidr.strip(), strict=True) for cidr in internal_cidrs
    )
    parsed: SplitResult = urlsplit(api_url)
    api_port: int | None = None
    if parsed.hostname and parsed.scheme in {"http", "https"}:
        api_port = (
            parsed.port
            if parsed.port is not None
            else (443 if parsed.scheme == "https" else 80)
        )
    return DestinationPolicyConfig(
        api_host=parsed.hostname, api_port=api_port, internal_networks=networks
    )


def is_internal(config: DestinationPolicyConfig, address: IPAddress) -> bool:
    embedded: IPAddress = _embedded_address(address)
    return (
        not address.is_global
        or not embedded.is_global
        or any(
            address in network or embedded in network
            for network in config.internal_networks
        )
    )


def resolve_destination(
    config: DestinationPolicyConfig, host: str, port: int
) -> tuple[str, ...] | None:
    """Return all validated addresses in DNS order, or None if any is blocked."""
    host = host.strip().lower()
    if not host or not 1 <= port <= 65535:
        return None
    addresses: list[IPAddress]
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            answers: Sequence[
                tuple[int, int, int, str, tuple[str | int | bytes, ...]]
            ] = socket.getaddrinfo(
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            addresses = [ipaddress.ip_address(str(answer[4][0])) for answer in answers]
        except (OSError, ValueError):
            return None
    if not addresses:
        return None
    is_api: bool = host == config.api_host and port == config.api_port
    if not is_api and any(is_internal(config, address) for address in addresses):
        return None
    return tuple(dict.fromkeys(str(address) for address in addresses))


def is_destination_blocked(
    config: DestinationPolicyConfig, host: str, port: int
) -> bool:
    return resolve_destination(config, host, port) is None


def pin_destination(host: str, port: int, addresses: tuple[str, ...]) -> None:
    """Pin the connection in the same task as mitmproxy's server_connect hook.

    Real TLS tests guard this task-context dependency when mitmproxy changes.
    """
    if not isinstance(asyncio.get_running_loop(), UpstreamEventLoop):
        raise RuntimeError(
            "Sandbox proxy requires UpstreamEventLoop for address pinning"
        )
    _destination.set((host, port, addresses))


def clear_destination() -> None:
    _destination.set(None)


class UpstreamEventLoop(asyncio.SelectorEventLoop):
    async def getaddrinfo(
        self,
        host: str | bytes | None,
        port: str | bytes | int | None,
        *,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[_RetAddress]:
        destination: tuple[str, int, tuple[str, ...]] | None = _destination.get()
        if destination is not None:
            pinned_host, pinned_port, addresses = destination
            if (host, port) == (pinned_host, pinned_port):
                answers: list[_RetAddress] = []
                for address in addresses:
                    address_family: int = (
                        socket.AF_INET6
                        if ipaddress.ip_address(address).version == 6
                        else socket.AF_INET
                    )
                    if family not in {socket.AF_UNSPEC, address_family}:
                        continue
                    answers.extend(
                        await super().getaddrinfo(
                            address,
                            port,
                            family=family,
                            type=type,
                            proto=proto,
                            flags=flags | socket.AI_NUMERICHOST,
                        )
                    )
                return answers
        return await super().getaddrinfo(
            host, port, family=family, type=type, proto=proto, flags=flags
        )
