"""Exercise destination pinning through mitmproxy's real TLS connection path."""

import asyncio
import datetime as dt
import socket
import ssl
from contextlib import suppress
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from mitmproxy import tls
from mitmproxy.proxy import server_hooks

from onyx.sandbox_proxy import server
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import (
    UpstreamEventLoop,
    parse_destination_policy,
)
from tests.unit.sandbox_proxy.conftest import (
    NoMatchedRequest,
    RecordingCredentialResolver,
    StubResolver,
    make_resolved_sandbox,
    unused_cache,
    wait_for_proxy_listener,
)

_HOST: str = "upstream.test"


class _Connections:
    def __init__(self) -> None:
        self.peers: list[tuple[str, int]] = []
        self.tls_errors: list[str] = []

    def server_connected(self, data: server_hooks.ServerConnectionHookData) -> None:
        assert data.server.peername is not None
        self.peers.append(data.server.peername[:2])

    def tls_failed_server(self, data: tls.TlsData) -> None:
        assert data.conn.error is not None
        self.tls_errors.append(data.conn.error)


def _tls_context(tmp_path: Path, hostname: str) -> tuple[ssl.SSLContext, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "upstream.crt"
    key_path = tmp_path / "upstream.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, cert_path


def _mock_dns(monkeypatch: pytest.MonkeyPatch, loopback: str) -> None:
    def resolve(
        host: str | bytes | None,
        port: str | bytes | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[str, int] | tuple[str, int, int, int]]]:
        assert host in {_HOST, loopback}
        assert isinstance(port, int)
        assert family in {socket.AF_UNSPEC, socket.AF_INET, socket.AF_INET6}
        assert type in {0, socket.SOCK_STREAM}
        assert proto in {0, socket.IPPROTO_TCP}
        assert flags in {0, socket.AI_NUMERICHOST}
        # Only the policy may resolve the hostname; TCP uses its numeric pin.
        if host == _HOST and proto != socket.IPPROTO_TCP:
            raise socket.gaierror("TCP connection bypassed the address pin")
        if loopback == "::1":
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (loopback, port, 0, 0),
                )
            ]
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (loopback, port),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


async def _send_connect(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, port: int
) -> None:
    writer.write(
        f"CONNECT {_HOST}:{port} HTTP/1.1\r\nHost: {_HOST}:{port}\r\n\r\n".encode()
    )
    await writer.drain()
    response: bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    assert response.startswith(b"HTTP/1.1 200")


async def _send_get(
    writer: asyncio.StreamWriter, port: int, *, keep_alive: bool
) -> None:
    connection: str = "keep-alive" if keep_alive else "close"
    writer.write(
        f"GET / HTTP/1.1\r\nHost: {_HOST}:{port}\r\n"
        f"Authorization: Bearer placeholder\r\nConnection: {connection}\r\n\r\n".encode()
    )
    await writer.drain()


async def _read_response(reader: asyncio.StreamReader) -> bytes:
    headers: bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    body: bytes = await asyncio.wait_for(reader.readexactly(2), timeout=10)
    return headers + body


@pytest.mark.parametrize("certificate_host", [_HOST, "wrong.test"])
@pytest.mark.parametrize("loopback", ["127.0.0.1", "::1"])
def test_pinned_tls_preserves_hostname_verification_and_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    certificate_host: str,
    loopback: str,
) -> None:
    async def exercise() -> None:
        context, upstream_ca = _tls_context(tmp_path, certificate_host)
        server_names: list[str | None] = []
        requests: list[bytes] = []

        def record_sni(
            _socket: ssl.SSLSocket | ssl.SSLObject,
            name: str | None,
            _context: object,
        ) -> None:
            server_names.append(name)

        context.set_servername_callback(record_sni)

        async def serve(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                while True:
                    try:
                        request = await reader.readuntil(b"\r\n\r\n")
                    except asyncio.IncompleteReadError:
                        return
                    requests.append(request)
                    close = len(requests) >= 2
                    connection = b"close" if close else b"keep-alive"
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: "
                        + connection
                        + b"\r\n\r\nok"
                    )
                    await writer.drain()
                    if close:
                        return
            finally:
                writer.close()
                await writer.wait_closed()

        upstream = await asyncio.start_server(serve, loopback, 0, ssl=context)
        upstream_port = upstream.sockets[0].getsockname()[1]

        _mock_dns(monkeypatch, loopback)
        monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_HOST", loopback)
        monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_PORT", 0)
        monkeypatch.setattr(server, "_MITM_CONFDIR", str(tmp_path / "mitm"))
        monkeypatch.setattr(
            server, "SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA", str(upstream_ca)
        )
        master = server._build_mitm_master()
        master.options.update(connection_strategy="eager")
        connected = _Connections()
        master.addons.add(connected)
        credential = RecordingCredentialResolver(
            headers={"Authorization": "Bearer injected"}
        )
        master.addons.add(
            GateAddon(
                identity=StubResolver(sandbox=make_resolved_sandbox()),
                request_evaluator=NoMatchedRequest(),
                cache_factory=unused_cache,
                proxy_instance_id="tls-test",
                credential_dispatcher=CredentialInjectionDispatcher([credential]),
                destination_policy=parse_destination_policy(
                    f"https://{_HOST}:{upstream_port}"
                ),
            )
        )
        task = asyncio.create_task(master.run())
        writer: asyncio.StreamWriter | None = None
        try:
            port: int = await wait_for_proxy_listener(master, task)
            reader: asyncio.StreamReader
            reader, writer = await asyncio.open_connection(loopback, port)
            await _send_connect(reader, writer, upstream_port)
            client_context = ssl.create_default_context(
                cafile=str(tmp_path / "mitm" / "mitmproxy-ca-cert.pem")
            )
            responses: list[bytes] = []
            try:
                await asyncio.wait_for(
                    writer.start_tls(client_context, server_hostname=_HOST), timeout=10
                )
            except (ssl.SSLError, ConnectionError):
                if certificate_host == _HOST:
                    raise
            else:
                for index in range(2 if certificate_host == _HOST else 1):
                    await _send_get(
                        writer,
                        upstream_port,
                        keep_alive=index == 0 and certificate_host == _HOST,
                    )
                    if certificate_host != _HOST:
                        responses.append(
                            await asyncio.wait_for(reader.read(), timeout=10)
                        )
                    else:
                        responses.append(await _read_response(reader))
            assert server_names == [_HOST]
            assert connected.peers == [(loopback, upstream_port)]
            if certificate_host != _HOST:
                if responses:
                    assert responses[0].startswith(b"HTTP/1.1 502")
                assert any(
                    "hostname mismatch" in error for error in connected.tls_errors
                )
                assert not requests
                return
            assert not connected.tls_errors
            assert len(responses) == 2
            assert all(
                response.startswith(b"HTTP/1.1 200") and response.endswith(b"ok")
                for response in responses
            )
            assert len(requests) == 2
            assert all(
                b"Authorization: Bearer injected\r\n" in request
                and b"placeholder" not in request
                for request in requests
            )
            assert len(credential.resolve_calls) == 2
        finally:
            if writer is not None:
                writer.close()
                with suppress(ssl.SSLError, ConnectionError):
                    await writer.wait_closed()
            master.shutdown()
            await task
            upstream.close()
            await upstream.wait_closed()

    asyncio.run(exercise(), loop_factory=UpstreamEventLoop)
