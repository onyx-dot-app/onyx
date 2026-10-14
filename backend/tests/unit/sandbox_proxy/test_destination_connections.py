"""Exercise destination enforcement through real proxy and upstream sockets."""

from __future__ import annotations

import asyncio
import socket
import ssl
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
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.resolvers.mcp_matching import CraftMCPTarget
from onyx.sandbox_proxy.resolvers.mcp_server import MCPServerResolver
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
    address: str, port: int = 0, ssl_context: ssl.SSLContext | None = None
) -> AsyncIterator[tuple[int, list[bytes]]]:
    requests: list[bytes] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        index: int = len(requests)
        requests.append(b"")  # Count accepted connections, including empty requests.
        try:
            try:
                requests[index] = await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError as exc:
                requests[index] = exc.partial
                return
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    upstream: asyncio.Server = await asyncio.start_server(
        serve, address, port, ssl=ssl_context
    )
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
    mcp_resolver: MCPServerResolver | None = None,
    evaluator: RequestEvaluator | None = None,
    dispatcher: CredentialInjectionDispatcher | None = None,
    connection_strategy: str = "eager",
) -> AsyncIterator[int]:
    monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_HOST", address)
    monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_PORT", 0)
    monkeypatch.setattr(server, "_MITM_CONFDIR", str(tmp_path / f"mitm-{api_port}"))
    master: DumpMaster = server._build_mitm_master()
    master.options.update(connection_strategy=connection_strategy)
    if addresses is not None:
        master.addons.add(addresses)
    master.addons.add(
        GateAddon(
            mcp_resolver=mcp_resolver,
            identity=StubResolver(sandbox=make_resolved_sandbox()),
            request_evaluator=evaluator or NoMatchedRequest(),
            cache_factory=unused_cache,
            proxy_instance_id="connection-test",
            credential_dispatcher=dispatcher or CredentialInjectionDispatcher([]),
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


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
@pytest.mark.usefixtures("mcp_ssrf_settings")
def test_private_http_mcp_uses_pinned_addresses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: str
) -> None:
    async def exercise() -> None:
        async with _upstream(address) as (port, requests):
            resolver = MCPServerResolver()
            monkeypatch.setattr(
                resolver,
                "_load_targets",
                lambda _tenant: (
                    CraftMCPTarget(
                        server_id=1,
                        scheme="http",
                        host=_HOST,
                        port=port,
                        path_prefix="",
                    ),
                ),
            )
            monkeypatch.setattr(
                resolver, "_load_accessible_ids", lambda _tenant, _user: frozenset({1})
            )
            unpinned = _dns(monkeypatch, lambda _port: (address,), lambda _port: ())
            async with _proxy(
                monkeypatch, tmp_path, address, 1, mcp_resolver=resolver
            ) as proxy_port:
                response = await _request(address, proxy_port, port)
            assert response.startswith(b"HTTP/1.1 200")
            assert len(requests) == 1
            assert not unpinned

    with asyncio.Runner(loop_factory=UpstreamEventLoop) as runner:
        runner.run(exercise())


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("connection_strategy", ["eager", "lazy"])
@pytest.mark.parametrize("tls_payload", [False, True])
@pytest.mark.usefixtures("mcp_ssrf_settings")
def test_private_connect_never_forwards_raw_tcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    address: str,
    connection_strategy: str,
    tls_payload: bool,
) -> None:
    from tests.unit.sandbox_proxy.test_destination_tls import _tls_context

    context, ca = _tls_context(tmp_path, _HOST)
    monkeypatch.setattr(server, "SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA", str(ca))

    async def exercise() -> None:
        async with _upstream(address, ssl_context=context if tls_payload else None) as (
            port,
            requests,
        ):
            resolver = MCPServerResolver()
            monkeypatch.setattr(
                resolver,
                "_load_targets",
                lambda _tenant: (
                    CraftMCPTarget(
                        server_id=1,
                        scheme="https",
                        host=_HOST,
                        port=port,
                        path_prefix="/mcp",
                    ),
                ),
            )
            monkeypatch.setattr(
                resolver, "_load_accessible_ids", lambda _tenant, _user: frozenset({1})
            )
            _dns(monkeypatch, lambda _port: (address,), lambda _port: ())
            async with _proxy(
                monkeypatch,
                tmp_path,
                address,
                1,
                mcp_resolver=resolver,
                connection_strategy=connection_strategy,
            ) as proxy_port:
                reader, writer = await asyncio.open_connection(address, proxy_port)
                try:
                    writer.write(
                        f"CONNECT {_HOST}:{port} HTTP/1.1\r\nHost: {_HOST}:{port}\r\n\r\n".encode()
                    )
                    await writer.drain()
                    response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
                    assert response.startswith(b"HTTP/1.1 200")
                    if tls_payload:
                        client_context = ssl.create_default_context(
                            cafile=str(tmp_path / "mitm-1" / "mitmproxy-ca-cert.pem")
                        )
                        await asyncio.wait_for(
                            writer.start_tls(client_context, server_hostname=_HOST), 10
                        )
                    writer.write(b"SSH-2.0-policy-bypass\r\n\r\n")
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 10)
                    assert b"200 OK" not in response
                finally:
                    writer.close()
                    await writer.wait_closed()
            assert not any(requests), "Non-HTTP payload reached the private upstream"

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("case", ["plumbing", "outside_path", "denied_tool"])
@pytest.mark.usefixtures("mcp_ssrf_settings")
def test_private_mcp_http_enforces_path_credentials_and_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: str, case: str
) -> None:
    import json
    from unittest.mock import MagicMock

    from onyx.db.enums import (
        EndpointPolicy,
        MCPAuthenticationPerformer,
        MCPAuthenticationType,
    )
    from onyx.db.models import MCPServer, User
    from onyx.sandbox_proxy import request_evaluator
    from onyx.sandbox_proxy.resolvers import mcp_server
    from onyx.server.features.mcp.credentials import ResolvedMCPCredentials

    async def exercise() -> None:
        async with _upstream(address) as (port, requests):
            stored = MCPServer(
                id=1,
                name="Private MCP",
                server_url=f"http://{_HOST}:{port}/mcp",
                available_in_craft=True,
                auth_type=MCPAuthenticationType.API_TOKEN,
                auth_performer=MCPAuthenticationPerformer.ADMIN,
            )
            user = User(id=make_resolved_sandbox().user_id)
            for module in (request_evaluator, mcp_server):
                monkeypatch.setattr(module, "get_session_with_tenant", MagicMock())
                monkeypatch.setattr(
                    module, "get_craft_enabled_mcp_servers", lambda *_args: [stored]
                )
                monkeypatch.setattr(module, "fetch_user_by_id", lambda *_args: user)
            monkeypatch.setattr(
                request_evaluator,
                "get_action_policies",
                lambda *_args: {"delete_records": EndpointPolicy.DENY},
            )
            monkeypatch.setattr(
                mcp_server, "get_mcp_server_by_id", lambda *_args: stored
            )
            monkeypatch.setattr(
                mcp_server, "user_can_access_mcp_server", lambda *_args: True
            )
            credentials = MagicMock(
                return_value=ResolvedMCPCredentials(
                    connection_config_id=1,
                    connection_data={
                        "headers": {"Authorization": "Bearer real-test-token"}
                    },
                    user_oauth_token=None,
                    auth_type=MCPAuthenticationType.API_TOKEN,
                )
            )
            monkeypatch.setattr(mcp_server, "resolve_mcp_credentials", credentials)
            resolver = MCPServerResolver()
            _dns(monkeypatch, lambda _port: (address,), lambda _port: ())
            async with _proxy(
                monkeypatch,
                tmp_path,
                address,
                1,
                mcp_resolver=resolver,
                evaluator=request_evaluator.McpRequestEvaluator(),
                dispatcher=CredentialInjectionDispatcher([resolver]),
            ) as proxy_port:
                reader, writer = await asyncio.open_connection(address, proxy_port)
                path = "/admin" if case == "outside_path" else "/mcp"
                body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call"
                        if case == "denied_tool"
                        else "initialize",
                        "params": {"name": "delete_records"},
                    }
                ).encode()
                try:
                    writer.write(
                        f"POST http://{_HOST}:{port}{path} HTTP/1.1\r\nHost: {_HOST}:{port}\r\nContent-Type: application/json\r\nAuthorization: Bearer placeholder\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                        + body
                    )
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 10)
                finally:
                    writer.close()
                    await writer.wait_closed()
            if case == "plumbing":
                assert response.startswith(b"HTTP/1.1 200")
                assert len(requests) == 1
                assert b"Authorization: Bearer real-test-token" in requests[0]
                assert b"placeholder" not in requests[0]
                credentials.assert_called_once()
            else:
                assert response.startswith(b"HTTP/1.1 403")
                assert (
                    b"credential_error" in response
                    if case == "outside_path"
                    else b"policy_denied" in response
                )
                assert not any(requests)
                credentials.assert_not_called()

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
