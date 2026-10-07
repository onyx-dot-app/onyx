from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from onyx.sandbox_proxy.destination_policy import (
    UpstreamEventLoop,
    clear_destination,
    parse_destination_policy,
    pin_destination,
    resolve_destination,
)

if TYPE_CHECKING:
    from socket import _RetAddress


@pytest.fixture
def resolver_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str | bytes | None, str | bytes | int | None, int]]:
    calls: list[tuple[str | bytes | None, str | bytes | int | None, int]] = []

    async def resolve(
        _loop: asyncio.SelectorEventLoop,
        host: str | bytes | None,
        port: str | bytes | int | None,
        *,
        flags: int = 0,
        **_kwargs: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        calls.append((host, port, flags))
        return []

    monkeypatch.setattr(asyncio.SelectorEventLoop, "getaddrinfo", resolve)
    return calls


@pytest.mark.parametrize(
    "host,port,expected_host,expected_flags",
    [
        ("origin.example", 443, "8.8.8.8", socket.AI_NUMERICHOST),
        ("origin.example", 80, "origin.example", 0),
        ("database.example", 443, "database.example", 0),
    ],
)
def test_only_exact_destination_uses_numeric_pin(
    resolver_calls: list[tuple[str | bytes | None, str | bytes | int | None, int]],
    host: str,
    port: int,
    expected_host: str,
    expected_flags: int,
) -> None:
    async def exercise() -> None:
        pin_destination("origin.example", 443, ("8.8.8.8",))
        await asyncio.get_running_loop().getaddrinfo(host, port)
        clear_destination()
        await asyncio.get_running_loop().getaddrinfo("origin.example", 443)

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
    assert resolver_calls == [
        (expected_host, port, expected_flags),
        ("origin.example", 443, 0),
    ]


def test_pin_requires_compatible_loop() -> None:
    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="requires UpstreamEventLoop"):
            pin_destination("origin.example", 443, ("8.8.8.8",))

    asyncio.run(exercise())


def test_concurrent_connection_pins_are_isolated(
    resolver_calls: list[tuple[str | bytes | None, str | bytes | int | None, int]],
) -> None:
    async def connect(address: str) -> None:
        pin_destination("origin.example", 443, (address,))
        await asyncio.sleep(0)
        await asyncio.get_running_loop().getaddrinfo("origin.example", 443)

    async def exercise() -> None:
        await asyncio.gather(connect("8.8.8.8"), connect("1.1.1.1"))
        await asyncio.get_running_loop().getaddrinfo("origin.example", 443)

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
    assert [call[0] for call in resolver_calls] == [
        "8.8.8.8",
        "1.1.1.1",
        "origin.example",
    ]


@pytest.mark.parametrize(
    "family,expected",
    [
        (socket.AF_UNSPEC, ["2606:4700:4700::1111", "8.8.8.8"]),
        (socket.AF_INET, ["8.8.8.8"]),
        (socket.AF_INET6, ["2606:4700:4700::1111"]),
    ],
)
def test_pinned_answers_preserve_order_and_requested_family(
    resolver_calls: list[tuple[str | bytes | None, str | bytes | int | None, int]],
    family: int,
    expected: list[str],
) -> None:
    async def exercise() -> None:
        pin_destination("origin.example", 443, ("2606:4700:4700::1111", "8.8.8.8"))
        await asyncio.get_running_loop().getaddrinfo(
            "origin.example", 443, family=family
        )

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
    assert resolver_calls == [
        (address, 443, socket.AI_NUMERICHOST) for address in expected
    ]


@pytest.mark.parametrize(
    "live_host,refused_host", [("127.0.0.1", "::1"), ("::1", "127.0.0.1")]
)
def test_connection_falls_back_without_resolving_hostname_again(
    monkeypatch: pytest.MonkeyPatch, live_host: str, refused_host: str
) -> None:
    original_getaddrinfo: Callable[..., list[_RetAddress]] = socket.getaddrinfo
    hostname_lookups: list[str] = []

    def resolve(host: str, port: int, *args: int, **kwargs: int) -> list[_RetAddress]:
        if host == "origin.example":
            hostname_lookups.append(host)
            return [
                answer
                for address in (refused_host, live_host)
                for answer in original_getaddrinfo(
                    address, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
                )
            ]
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    async def serve(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.write(b"fallback works")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def exercise() -> None:
        upstream: asyncio.Server = await asyncio.start_server(serve, live_host, 0)
        port: int = upstream.sockets[0].getsockname()[1]
        # Check the other family's port is free, then close it to get refusal.
        with socket.socket(
            socket.AF_INET6 if ":" in refused_host else socket.AF_INET
        ) as refused:
            refused.bind((refused_host, port))
        try:
            addresses = resolve_destination(
                parse_destination_policy(f"http://origin.example:{port}"),
                "origin.example",
                port,
            )
            assert addresses == (refused_host, live_host)
            pin_destination("origin.example", port, addresses)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("origin.example", port), timeout=5
            )
            try:
                assert (
                    await asyncio.wait_for(reader.read(), timeout=5)
                    == b"fallback works"
                )
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            upstream.close()
            await upstream.wait_closed()

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
    assert hostname_lookups == ["origin.example"]
