"""Exercise destination enforcement through real proxy and upstream sockets."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from mitmproxy.proxy import server_hooks
from mitmproxy.tools.dump import DumpMaster

from onyx.sandbox_proxy import server
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import (
    UpstreamEventLoop,
    parse_destination_policy,
)
from tests.unit.sandbox_proxy.conftest import (
    NoMatchedRequest,
    StubResolver,
    make_resolved_sandbox,
    unused_cache,
    wait_for_proxy_listener,
)

if TYPE_CHECKING:
    from socket import _RetAddress

_HOST: str = "upstream.test"


@asynccontextmanager
async def _upstream(
    address: str, port: int = 0
) -> AsyncIterator[tuple[int, list[bytes]]]:
    requests: list[bytes] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        index: int = len(requests)
        requests.append(b"")  # Count accepted connections, including empty requests.
        try:
            requests[index] = await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    upstream: asyncio.Server = await asyncio.start_server(serve, address, port)
    try:
        yield upstream.sockets[0].getsockname()[1], requests
    finally:
        upstream.close()
        await upstream.wait_closed()


@asynccontextmanager
async def _proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    address: str,
    api_port: int,
    barrier: "_ConnectionBarrier | None" = None,
    addresses: "_ConnectionAddresses | None" = None,
) -> AsyncIterator[int]:
    monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_HOST", address)
    monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_PORT", 0)
    monkeypatch.setattr(server, "_MITM_CONFDIR", str(tmp_path / f"mitm-{api_port}"))
    master: DumpMaster = server._build_mitm_master()
    if addresses is not None:
        master.addons.add(addresses)
    master.addons.add(
        GateAddon(
            identity=StubResolver(sandbox=make_resolved_sandbox()),
            request_evaluator=NoMatchedRequest(),
            cache_factory=unused_cache,
            proxy_instance_id="connection-test",
            credential_dispatcher=CredentialInjectionDispatcher([]),
            destination_policy=parse_destination_policy(f"http://{_HOST}:{api_port}"),
        )
    )
    if barrier is not None:
        master.addons.add(barrier)
    task: asyncio.Task[None] = asyncio.create_task(master.run())
    try:
        yield await wait_for_proxy_listener(master, task)
    finally:
        master.shutdown()
        await task


async def _request(address: str, proxy_port: int, upstream_port: int) -> bytes:
    reader, writer = await asyncio.open_connection(address, proxy_port)
    try:
        writer.write(
            f"GET http://{_HOST}:{upstream_port}/ HTTP/1.1\r\n"
            f"Host: {_HOST}:{upstream_port}\r\nConnection: close\r\n\r\n".encode()
        )
        await writer.drain()
        return await asyncio.wait_for(reader.read(), timeout=10)
    finally:
        writer.close()
        await writer.wait_closed()


def _dns(
    monkeypatch: pytest.MonkeyPatch,
    policy_answers: Callable[[int], tuple[str, ...]],
    connection_answers: Callable[[int], tuple[str, ...]],
) -> list[int]:
    original: Callable[..., list[_RetAddress]] = socket.getaddrinfo
    unpinned: list[int] = []

    def resolve(
        host: str | bytes | None,
        port: str | bytes | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[_RetAddress]:
        if host != _HOST:
            return original(host, port, family, type, proto, flags)
        assert isinstance(port, int)
        if proto == socket.IPPROTO_TCP:
            addresses: tuple[str, ...] = policy_answers(port)
        else:
            unpinned.append(port)
            addresses = connection_answers(port)
        answers: list[_RetAddress] = []
        for address in addresses:
            address_family: int = socket.AF_INET6 if ":" in address else socket.AF_INET
            if family in {socket.AF_UNSPEC, address_family}:
                answers.extend(
                    original(
                        address,
                        port,
                        address_family,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        socket.AI_NUMERICHOST,
                    )
                )
        return answers

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return unpinned


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("mixed", [False, True])
def test_forbidden_dns_answers_never_reach_upstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: str, mixed: bool
) -> None:
    async def exercise() -> None:
        async with _upstream(address) as (port, requests):
            public: str = (
                "8.8.8.8" if address == "127.0.0.1" else "2606:4700:4700::1111"
            )
            answers: tuple[str, ...] = (public, address) if mixed else (address,)
            unpinned: list[int] = _dns(
                monkeypatch, lambda _port: answers, lambda _port: (address,)
            )
            # Port 1 keeps this destination outside the exact API exception.
            async with _proxy(monkeypatch, tmp_path, address, 1) as proxy_port:
                response: bytes = await _request(address, proxy_port, port)
            assert response.startswith(b"HTTP/1.1 403")
            assert requests == []
            assert unpinned == []

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_rebinding_cannot_connect_to_unvalidated_upstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: str
) -> None:
    async def exercise() -> None:
        rebound: str = "::1" if address == "127.0.0.1" else "127.0.0.1"
        async with (
            _upstream(address) as (port, requests),
            _upstream(rebound, port) as (_, forbidden),
        ):
            unpinned: list[int] = _dns(
                monkeypatch, lambda _port: (address,), lambda _port: (rebound,)
            )
            async with _proxy(monkeypatch, tmp_path, address, port) as proxy_port:
                response: bytes = await _request(address, proxy_port, port)
            assert response.startswith(b"HTTP/1.1 200") and response.endswith(b"ok")
            assert forbidden == []
            assert len(requests) == 1
            assert unpinned == []

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_proxy_falls_back_to_second_validated_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: str
) -> None:
    async def exercise() -> None:
        refused: str = "::1" if address == "127.0.0.1" else "127.0.0.1"
        async with _upstream(address) as (port, requests):
            # Bind without listening so the first answer deterministically refuses TCP.
            with socket.socket(
                socket.AF_INET6 if ":" in refused else socket.AF_INET,
                socket.SOCK_STREAM,
            ) as reservation:
                reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                reservation.bind((refused, port))
                unpinned: list[int] = _dns(
                    monkeypatch,
                    lambda _port: (refused, address),
                    lambda _port: (refused,),
                )
                async with _proxy(monkeypatch, tmp_path, address, port) as proxy_port:
                    response: bytes = await _request(address, proxy_port, port)
            assert response.startswith(b"HTTP/1.1 200") and response.endswith(b"ok")
            assert len(requests) == 1
            assert unpinned == []

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)


class _ConnectionBarrier:
    def __init__(self) -> None:
        self.entered: int = 0
        self.ready: asyncio.Event = asyncio.Event()

    async def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:
        assert data.server.error is None
        self.entered += 1
        if self.entered == 2:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=10)


class _ConnectionAddresses:
    """Give simultaneous connections distinct DNS answers before validation."""

    def __init__(self) -> None:
        self.address: ContextVar[str] = ContextVar(
            "test_dns_address", default="127.0.0.1"
        )
        self.entered: int = 0

    def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:  # noqa: ARG002
        self.address.set("127.0.0.1" if self.entered == 0 else "::1")
        self.entered += 1


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_concurrent_connections_keep_their_own_pins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: str
) -> None:
    async def exercise() -> None:
        async with (
            _upstream("127.0.0.1") as (v4_port, v4_requests),
            _upstream("::1", v4_port) as (_, v6_requests),
        ):
            addresses: _ConnectionAddresses = _ConnectionAddresses()
            unpinned: list[int] = _dns(
                monkeypatch, lambda _port: (addresses.address.get(),), lambda _port: ()
            )
            barrier: _ConnectionBarrier = _ConnectionBarrier()
            async with _proxy(
                monkeypatch, tmp_path, address, v4_port, barrier, addresses
            ) as proxy_port:
                responses: tuple[bytes, bytes] = await asyncio.gather(
                    _request(address, proxy_port, v4_port),
                    _request(address, proxy_port, v4_port),
                )
            assert barrier.entered == 2
            assert all(
                response.startswith(b"HTTP/1.1 200") and response.endswith(b"ok")
                for response in responses
            )
            assert len(v4_requests) == len(v6_requests) == 1
            assert unpinned == []

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
