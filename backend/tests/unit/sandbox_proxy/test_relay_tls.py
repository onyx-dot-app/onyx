"""The relay mTLS listener: only relay certificates from the relay CA, with a
pinned SAN, reach the proxy port."""

import asyncio
import datetime as dt
import os
import ssl
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from onyx.sandbox_proxy import server
from onyx.sandbox_proxy.relay_tls import (
    RelayTLSConfig,
    RelayTLSListener,
    loopback_for,
)
from onyx.server.features.build.configs import SandboxRuntime

_RELAY_SAN = "onyx-craft-fc-relay.onyx-sandbox-runtime.svc"
_PROXY_SAN = "localhost"


@dataclass
class _CA:
    name: str
    key: ec.EllipticCurvePrivateKey
    cert: x509.Certificate

    @classmethod
    def new(cls, name: str) -> "_CA":
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(hours=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        return cls(name=name, key=key, cert=cert)

    def write_leaf(
        self, dir: Path, name: str, san: str, server: bool
    ) -> tuple[str, str]:
        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.timezone.utc)
        usage = (
            ExtendedKeyUsageOID.SERVER_AUTH
            if server
            else ExtendedKeyUsageOID.CLIENT_AUTH
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, san)]))
            .issuer_name(self.cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(hours=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False
            )
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    self.key.public_key()
                ),
                critical=False,
            )
            .sign(self.key, hashes.SHA256())
        )
        cert_path, key_path = dir / f"{name}.crt", dir / f"{name}.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return str(cert_path), str(key_path)

    def write(self, dir: Path) -> str:
        path = dir / f"{self.name}-ca.crt"
        path.write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        return str(path)


@dataclass
class _Setup:
    tmp: Path
    proxy_ca: _CA
    relay_ca: _CA
    other_ca: _CA
    upstream_port: int
    upstream_conns: list[bytes]

    def config(self, allowed_sans: frozenset[str]) -> RelayTLSConfig:
        cert, key = self.proxy_ca.write_leaf(self.tmp, "proxy", _PROXY_SAN, server=True)
        return RelayTLSConfig(
            port=0,
            cert_path=cert,
            key_path=key,
            client_ca_path=self.relay_ca.write(self.tmp),
            allowed_sans=allowed_sans,
        )

    def client_context(
        self, signer: _CA | None, san: str = _RELAY_SAN
    ) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=self.proxy_ca.write(self.tmp))
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        if signer is not None:
            cert, key = signer.write_leaf(
                self.tmp, f"client-{signer.name}-{san}", san, server=False
            )
            context.load_cert_chain(cert, key)
        return context


@pytest_asyncio.fixture
async def setup(tmp_path: Path) -> AsyncIterator[_Setup]:
    """An echo upstream in place of the mitmproxy port. It records the bytes
    of each connection."""
    conns: list[bytes] = []

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        conns.append(data)
        writer.write(b"echo:" + data)
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    yield _Setup(
        tmp=tmp_path,
        proxy_ca=_CA.new("proxy"),
        relay_ca=_CA.new("relay"),
        other_ca=_CA.new("other"),
        upstream_port=upstream.sockets[0].getsockname()[1],
        upstream_conns=conns,
    )
    upstream.close()
    await upstream.wait_closed()


async def _listener(setup: _Setup, allowed_sans: frozenset[str]) -> RelayTLSListener:
    listener = RelayTLSListener(
        setup.config(allowed_sans),
        listen_host="127.0.0.1",
        upstream_host="127.0.0.1",
        upstream_port=setup.upstream_port,
    )
    await listener.start()
    return listener


async def _exchange(port: int, context: ssl.SSLContext) -> bytes:
    """Sends one message; returns the answer, or b"" if the proxy refused."""
    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=context, server_hostname=_PROXY_SAN
        )
        writer.write(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=5)
        writer.close()
        return data
    except (ssl.SSLError, ConnectionError):
        return b""


@pytest.mark.asyncio
async def test_relay_certificate_reaches_the_proxy_port(setup: _Setup) -> None:
    listener = await _listener(setup, frozenset({_RELAY_SAN}))
    try:
        answer = await _exchange(listener.port, setup.client_context(setup.relay_ca))
    finally:
        await listener.close()

    assert answer == b"echo:CONNECT example.com:443 HTTP/1.1\r\n\r\n"
    assert len(setup.upstream_conns) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    ["no client certificate", "another CA", "wrong SAN"],
)
async def test_other_clients_never_reach_the_proxy_port(
    setup: _Setup, client: str
) -> None:
    contexts = {
        "no client certificate": setup.client_context(None),
        "another CA": setup.client_context(setup.other_ca),
        # From the relay CA, but not the pinned relay name.
        "wrong SAN": setup.client_context(
            setup.relay_ca, "onyx-craft-fc-client.onyx.svc"
        ),
    }
    listener = await _listener(setup, frozenset({_RELAY_SAN}))
    try:
        answer = await _exchange(listener.port, contexts[client])
    finally:
        await listener.close()

    assert answer == b""
    assert setup.upstream_conns == []


@pytest.mark.asyncio
async def test_no_pin_accepts_any_certificate_from_the_client_ca(
    setup: _Setup,
) -> None:
    listener = await _listener(setup, frozenset())
    try:
        answer = await _exchange(
            listener.port, setup.client_context(setup.relay_ca, "own-pki.example")
        )
    finally:
        await listener.close()

    assert answer.startswith(b"echo:")


def test_unloadable_files_fail_at_start(setup: _Setup) -> None:
    config = setup.config(frozenset())
    bad = RelayTLSConfig(
        port=0,
        cert_path=config.cert_path,
        key_path=config.client_ca_path,
        client_ca_path=config.client_ca_path,
        allowed_sans=frozenset(),
    )
    with pytest.raises(ssl.SSLError):
        RelayTLSListener(bad, "127.0.0.1", "127.0.0.1", setup.upstream_port)


def test_config_needs_firecracker_and_all_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_PORT", 0)
    assert server._relay_tls_config() is None

    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_PORT", 8443)
    monkeypatch.setattr(server, "SANDBOX_RUNTIME", SandboxRuntime.POD)
    with pytest.raises(ValueError, match="SANDBOX_RUNTIME=firecracker"):
        server._relay_tls_config()

    monkeypatch.setattr(server, "SANDBOX_RUNTIME", SandboxRuntime.FIRECRACKER)
    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_CERT_PATH", "/c")
    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_KEY_PATH", "")
    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_CLIENT_CA_PATH", "/ca")
    with pytest.raises(ValueError, match="SANDBOX_PROXY_RELAY_TLS_KEY_PATH"):
        server._relay_tls_config()

    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_KEY_PATH", "/k")
    monkeypatch.setattr(server, "SANDBOX_PROXY_RELAY_TLS_ALLOWED_SANS", [_RELAY_SAN])
    config = server._relay_tls_config()
    assert config is not None
    assert config.allowed_sans == frozenset({_RELAY_SAN})


@pytest.mark.parametrize(
    ("listen_host", "expected"),
    [("0.0.0.0", "127.0.0.1"), ("::", "::1"), ("10.1.2.3", "10.1.2.3")],
)
def test_loopback_reaches_the_proxy_listener(listen_host: str, expected: str) -> None:
    assert loopback_for(listen_host) == expected


def _rotate_client_ca(setup: _Setup) -> None:
    """The client CA file now holds the other CA, with a newer mtime."""
    ca_path = setup.relay_ca.write(setup.tmp)
    Path(ca_path).write_bytes(Path(setup.other_ca.write(setup.tmp)).read_bytes())
    future = time.time() + 3600
    os.utime(ca_path, (future, future))


@pytest.mark.asyncio
async def test_rotated_client_ca_applies_without_restart(
    setup: _Setup, caplog: pytest.LogCaptureFixture
) -> None:
    listener = await _listener(setup, frozenset())
    try:
        before = await _exchange(listener.port, setup.client_context(setup.other_ca))
        _rotate_client_ca(setup)
        after = await _exchange(listener.port, setup.client_context(setup.other_ca))
    finally:
        await listener.close()

    assert before == b""
    assert after.startswith(b"echo:")
    assert "relay_tls_rejected reason=handshake" in caplog.text
