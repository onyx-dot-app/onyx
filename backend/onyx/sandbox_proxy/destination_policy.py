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
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
from onyx.sandbox_proxy.sandbox_identity.resolution import (
    PeerAddress,
    SandboxIdentityResolver,
    source_ip,
)
from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

if TYPE_CHECKING:
    from socket import _RetAddress

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

logger = setup_logger()

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
    config: DestinationPolicyConfig,
    host: str,
    port: int,
    *,
    scheme: str = "",
    peer: PeerAddress | None = None,
    identity: SandboxIdentityResolver | None = None,
    mcp_resolver: MCPServerResolver | None = None,
    upstream_addresses: tuple[str, ...] = (),
) -> tuple[str, ...] | None:
    """Validate existing upstream addresses, or resolve DNS once for a new connection.

    Internal MCP access requires source identity, exact origin, and tenant SSRF permission.
    Missing context denies the exception. Public and Onyx destinations need no MCP lookup.
    """
    host = host.strip().lower()
    if not host or not 1 <= port <= 65535:
        return None
    addresses: list[IPAddress]
    if upstream_addresses:
        try:
            addresses = [ipaddress.ip_address(ip) for ip in upstream_addresses]
        except ValueError:
            return None
    else:
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
                addresses = [
                    ipaddress.ip_address(str(answer[4][0])) for answer in answers
                ]
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Destination resolution failed host=%s port=%s: %s", host, port, exc
                )
                return None
    if not addresses:
        return None
    resolved = tuple(dict.fromkeys(str(address) for address in addresses))
    is_api = host == config.api_host and port == config.api_port
    if is_api or not any(is_internal(config, address) for address in addresses):
        return resolved

    if identity is None or mcp_resolver is None or scheme not in {"http", "https"}:
        return None
    try:
        src_ip = source_ip(peer)
        if src_ip is None:
            return None
        sandbox = identity.resolve_sandbox(src_ip)
        if sandbox is None or not mcp_resolver.allows_destination(
            sandbox, scheme, host, port
        ):
            return None
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(sandbox.tenant_id)
        try:
            params = outbound_ssrf_params(
                get_security_settings(allow_fallback=False).ssrf_protection_level
            )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    except Exception:
        logger.exception("mcp_destination_error host=%s port=%s", host, port)
        return None

    if not params.allow_private_network:
        return None
    # Validate the same answers that will be pinned, including embedded IPv4.
    for target in (host, *(str(_embedded_address(ip)) for ip in addresses)):
        authority = f"[{target}]" if ":" in target else target
        try:
            validate_outbound_http_url(
                f"{scheme}://{authority}:{port}",
                allow_private_network=params.allow_private_network,
                block_loopback_and_link_local=params.block_loopback_and_link_local,
                block_link_local_only=params.block_link_local_only,
                resolve_dns=False,
            )
        except (SSRFException, ValueError):
            return None
    return resolved


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
