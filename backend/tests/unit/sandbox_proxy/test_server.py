"""Unit tests for sandbox-proxy process configuration."""

import asyncio
import tempfile

import pytest
from mitmproxy import http
from mitmproxy.tools.dump import DumpMaster

from onyx.sandbox_proxy import server
from onyx.sandbox_proxy.destination_policy import is_destination_blocked
from onyx.sandbox_proxy.models import DestinationPolicyConfig
from tests.unit.sandbox_proxy.conftest import wait_for_proxy_listener


def test_mitm_options_use_custom_upstream_ca_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA",
        "/var/run/sandbox-proxy/upstream-ca-bundle.crt",
    )

    options = server._build_mitm_options()

    assert (
        options.ssl_verify_upstream_trusted_ca
        == "/var/run/sandbox-proxy/upstream-ca-bundle.crt"
    )
    assert options.ssl_insecure is False


def test_mitm_options_keep_default_trust_store_without_custom_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "SANDBOX_PROXY_SSL_VERIFY_UPSTREAM_TRUSTED_CA", None)

    options = server._build_mitm_options()

    assert options.ssl_verify_upstream_trusted_ca is None
    assert options.ssl_insecure is False


class _LocalResponse:
    def request(self, flow: http.HTTPFlow) -> None:
        flow.response = http.Response.make(200, b"listener test")


@pytest.mark.parametrize("allow_global", [False, True])
@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_proxy_port_accepts_configured_address_family(
    monkeypatch: pytest.MonkeyPatch, host: str, allow_global: bool
) -> None:
    # Exercise mitmproxy's real listener, not just its Options object.
    async def exercise() -> None:
        connect_host: str = "::1" if ":" in host else "127.0.0.1"
        with tempfile.TemporaryDirectory() as confdir:
            monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_HOST", host)
            monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_PORT", 0)
            monkeypatch.setattr(server, "_MITM_CONFDIR", confdir)
            monkeypatch.setattr(
                server, "SANDBOX_PROXY_ALLOW_GLOBAL_CLIENTS", allow_global
            )
            master: DumpMaster = server._build_mitm_master()
            assert master.options.block_global is not allow_global
            master.options.update(connection_strategy="lazy")
            master.addons.add(_LocalResponse())
            task: asyncio.Task[None] = asyncio.create_task(master.run())
            try:
                port: int = await wait_for_proxy_listener(master, task)
                reader: asyncio.StreamReader
                writer: asyncio.StreamWriter
                reader, writer = await asyncio.open_connection(connect_host, port)
                if host == "::":
                    with pytest.raises(ConnectionRefusedError):
                        await asyncio.open_connection("127.0.0.1", port)
                writer.write(
                    b"GET http://example.test/ HTTP/1.1\r\nHost: example.test\r\nConnection: close\r\n\r\n"
                )
                await writer.drain()
                response: bytes = await asyncio.wait_for(reader.read(), timeout=10)
                assert response.startswith(b"HTTP/1.1 200")
                assert response.endswith(b"listener test")
                writer.close()
                await writer.wait_closed()
            finally:
                master.shutdown()
                await task

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "setting",
    [
        "SANDBOX_PROXY_ALLOW_GLOBAL_CLIENTS",
        "SANDBOX_PROXY_LISTEN_HOST",
    ],
)
def test_ipv6_requires_internal_cidrs(
    monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    monkeypatch.setattr(server, "SANDBOX_PROXY_INTERNAL_CIDRS", "")
    monkeypatch.setattr(server, "SANDBOX_PROXY_ALLOW_GLOBAL_CLIENTS", False)
    monkeypatch.setattr(server, "SANDBOX_PROXY_LISTEN_HOST", "0.0.0.0")
    monkeypatch.setattr(server, setting, "::" if setting.endswith("HOST") else True)
    with pytest.raises(ValueError, match="INTERNAL_CIDRS is required"):
        server._build_destination_policy()


def test_startup_rejects_invalid_internal_cidrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "SANDBOX_PROXY_INTERNAL_CIDRS", "2600:ffff::/32,typo")
    with pytest.raises(ValueError):
        server._build_destination_policy()


def test_startup_uses_internal_cidrs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "SANDBOX_PROXY_INTERNAL_CIDRS", " 2600:ffff::/32 ,10.0.0.0/8"
    )
    policy: DestinationPolicyConfig = server._build_destination_policy()
    assert is_destination_blocked(policy, "2600:ffff::1", 443)
    assert not is_destination_blocked(policy, "2606:4700:4700::1111", 443)
